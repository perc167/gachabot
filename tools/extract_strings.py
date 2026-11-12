"""Collect every English line Paper can say into locales/catalog.json.

localize.py translates Paper's messages on their way out to Discord, so the
code keeps writing plain English and nothing has to be wrapped in a t() call.
For that it needs to know, ahead of time, every line the code can produce.
This reads the source (it never imports it) and writes them down:

  * plain strings that read like words to a person,
  * f-strings, with each {expression} turned into {0}, {1}... so one entry
    covers every value it can be filled with,
  * the docstrings of commands, because $help and the slash command picker
    show them, a paragraph at a time.

Multi-line strings are stored a line at a time, since that is how localize
matches them: a message is usually several strings glued together, and the
line is the piece that survives the gluing.

Run it after adding or changing messages, then translate whatever is new:
    python tools/extract_strings.py
    python tools/extract_strings.py --missing es   # lines es.json lacks
"""
import argparse
import ast
import inspect
import json
import re
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"
CATALOG = LOCALES / "catalog.json"
STRINGS = LOCALES / "strings"

# Top-level modules whose strings never reach Discord: SQL, word lists for
# guessing languages, the dashboard website, and this machinery itself.
SKIP_FILES = {"db.py", "smoke_test.py", "translator.py", "i18n.py", "localize.py",
              "oauth.py", "webparts.py", "anilist.py", "artcache.py"}

# Calls whose string arguments are for us, not for the people in a server.
QUIET_CALLS = {"debug", "info", "warning", "error", "exception", "critical",
               "print", "warn", "compile", "match", "search", "sub", "split",
               "findall", "fullmatch", "execute", "executemany", "executescript",
               "getenv", "get_pref", "set_pref", "get_player_pref", "set_player_pref",
               "strftime", "strptime", "getLogger", "add_check", "get_command",
               "startswith", "endswith", "replace", "strip", "lstrip", "rstrip",
               "join_path", "open", "Path", "fetch", "request", "get_setting",
               "set_setting", "has_feature", "Color", "Colour", "NamedTuple"}

# Keyword arguments that are on screen even when they are one word long:
# button labels, embed field names, footers, select options...
SHOWN_KEYWORDS = {"label", "title", "name", "value", "placeholder", "description",
                  "text", "content", "default", "help", "brief", "usage"}

SQL = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|PRAGMA|WITH)\b|"
                 r"\bFROM\s+\w+\s+WHERE\b|\b(INTEGER|TEXT|REAL)\b.*\b(NOT NULL|PRIMARY KEY|DEFAULT)\b|"
                 r"%\(\w+\)s")
CODEISH = re.compile(r"(\(\?|\\[dwsbS]|^https?://\S+$|^[\w./\\-]+\.(py|json|png|jpg|txt|db|gz)$"
                     r"|</?(div|span|html|body|script|style|a|p|td|tr)\b|^[\w:-]+:[\w:-]+$)")
WORDS = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
COMMAND_DECORATORS = ("command", "group", "hybrid_command", "hybrid_group")


def parents(tree):
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child._parent = node


def call_name(call) -> str:
    func = call.func
    return getattr(func, "attr", None) or getattr(func, "id", "") or ""


def is_command(func) -> bool:
    for deco in func.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        name = getattr(target, "attr", None) or getattr(target, "id", "")
        if name in COMMAND_DECORATORS:
            return True
    return False


def escape(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")


def from_format_string(text: str):
    """A plain string with {name} fields (filled later by .format) as a
    template with numbered fields, or None if it has no fields."""
    try:
        parsed = list(string.Formatter().parse(text))
    except ValueError:
        return None
    if not any(field is not None for _lit, field, _spec, _conv in parsed):
        return None
    out, seen = [], {}
    for literal, field, _spec, _conv in parsed:
        out.append(escape(literal))
        if field is not None:
            index = seen.setdefault(field, len(seen))
            out.append("{%d}" % index)
    return "".join(out)


def from_fstring(node: ast.JoinedStr) -> str:
    out, seen = [], {}
    for value in node.values:
        if isinstance(value, ast.Constant):
            out.append(escape(str(value.value)))
        else:
            key = ast.unparse(value.value)
            index = seen.setdefault(key, len(seen))
            out.append("{%d}" % index)
    return "".join(out)


def literal_text(template: str) -> str:
    """What a template says once its {fields} are taken out."""
    return re.sub(r"\{\d+\}", " ", template).replace("{{", "{").replace("}}", "}")


LONE_WORD = re.compile(r"[^\W\d_][^\W_]*[.!?…:]*", re.UNICODE)


def worth_keeping(line: str, one_word: int) -> bool:
    """one_word: 0 = a lone word is code, 1 = it is a label if Capitalised
    (button labels, field names), 2 = any word (the 'harem'/'harems' picked
    between inside an f-string)."""
    text = literal_text(line).strip()
    if not WORDS.findall(text):
        return False
    if SQL.search(line) or CODEISH.search(line.strip()):
        return False
    if not re.search(r"\s", re.sub(r"\{\d+\}", "", line)):
        # Without a space it is a label ("Claim", "Next") only when written
        # like one: command names, snake_case keys, paths and ALLCAPS
        # constants are code.
        if not one_word or not LONE_WORD.fullmatch(text) or text.isupper() and len(text) > 1:
            return False
        if one_word == 1 and not text[0].isupper():
            return False
    return True


def lines_of(template: str):
    """A template a line at a time, each line's fields renumbered from 0."""
    for raw in template.split("\n"):
        line = raw.strip()
        if not line:
            continue
        mapping = {}

        def renumber(match):
            old = match.group(1)
            return "{%d}" % mapping.setdefault(old, len(mapping))

        yield re.sub(r"(?<!\{)\{(\d+)\}(?!\})", renumber, line)


def paragraphs_of(doc: str):
    """A command's help, the way $help and the slash picker show it."""
    doc = inspect.cleandoc(doc)
    for paragraph in re.split(r"\n\s*\n", doc):
        rows = [r.strip() for r in paragraph.splitlines() if r.strip()]
        if not rows:
            continue
        # Lists and examples keep their lines; prose is reflowed into one.
        if any(re.match(r"([-*•>]|\d+[.)]|`|\$)", r) for r in rows[1:]):
            yield from (escape(r) for r in rows)
        else:
            yield escape(" ".join(rows))
    first = doc.splitlines()[0].strip() if doc.strip() else ""
    if first and first[-1] in ".!?:":
        yield escape(first)


def strings_in(path: Path):
    tree = ast.parse(path.read_text("utf-8"))
    parents(tree)
    docstrings = set()
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and is_command(node):
                    found += [(p, 1) for p in paragraphs_of(body[0].value.value)]

    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            template, inside_fstring = from_fstring(node), False
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            if isinstance(getattr(node, "_parent", None), ast.JoinedStr):
                continue           # a piece of an f-string, taken whole above
            template = from_format_string(node.value) or escape(node.value)
            inside_fstring = isinstance(getattr(node, "_parent", None), ast.IfExp) and \
                any(isinstance(a, ast.FormattedValue) for a in ancestors(node))
        else:
            continue
        if quiet(node) or SQL.search(template):
            continue
        parent = getattr(node, "_parent", None)
        shown = isinstance(parent, ast.keyword) and parent.arg in SHOWN_KEYWORDS
        in_tuple = isinstance(parent, (ast.Tuple, ast.List))
        # help's (command, what it does) pairs: the second can be one
        # lowercase word ("yours", "none") and is still words for a person.
        described = (isinstance(parent, ast.Tuple) and len(parent.elts) == 2
                     and parent.elts[1] is node and isinstance(parent.elts[0], ast.Constant))
        one_word = 2 if inside_fstring or described else 1 if (shown or in_tuple) else 0
        found += [(line, one_word) for line in lines_of(template)]
    return found


def ancestors(node):
    while hasattr(node, "_parent"):
        node = node._parent
        yield node


def quiet(node) -> bool:
    """Inside a log line, a regex, SQL, a dict lookup or a comparison."""
    for up in ancestors(node):
        if isinstance(up, ast.Call) and call_name(up) in QUIET_CALLS:
            return True
        if isinstance(up, (ast.Compare, ast.Subscript)):
            return True
        if isinstance(up, ast.Raise) and up.exc is not None:
            exc = up.exc.func if isinstance(up.exc, ast.Call) else up.exc
            # commands.BadArgument & co. are shown to people; bugs are not.
            if (getattr(exc, "id", "") or getattr(exc, "attr", "")) in (
                    "RuntimeError", "ValueError", "TypeError", "KeyError",
                    "AssertionError", "NotImplementedError", "SystemExit"):
                return True
        if isinstance(up, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            return False
    return False


def collect() -> list:
    files = sorted(ROOT.glob("cogs/*.py")) + sorted(
        p for p in ROOT.glob("*.py") if p.name not in SKIP_FILES)
    keep = set()
    for path in files:
        for line, one_word_ok in strings_in(path):
            if worth_keeping(line, one_word_ok):
                keep.add(line)
    # i18n.py's keyed messages, so they are translated by the same pass.
    english = json.loads((LOCALES / "en.json").read_text("utf-8"))
    for text in english.values():
        for line in lines_of(from_format_string(text) or escape(text)):
            keep.add(line)
    return sorted(keep)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--missing", metavar="LANG",
                        help="print the catalog lines LANG's file has no translation for")
    args = parser.parse_args()
    catalog = collect()
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=0), "utf-8")
    print(f"{len(catalog)} lines -> {CATALOG.relative_to(ROOT)}")
    if args.missing:
        path = STRINGS / f"{args.missing}.json"
        have = json.loads(path.read_text("utf-8")) if path.exists() else {}
        missing = [line for line in catalog if line not in have]
        json.dump(missing, sys.stdout, ensure_ascii=False, indent=0)
        print(f"\n{len(missing)} missing from {args.missing}", file=sys.stderr)


if __name__ == "__main__":
    main()
