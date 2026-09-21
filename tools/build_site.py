"""Builds the public site: every command, and how to set the bot up.

    python tools/build_site.py

One self-contained HTML file in site/. It is generated rather than written
by hand for the same reason the AutoMod list is: a command reference that
somebody edits separately is a command reference that is wrong within a week.
Everything on the page - the commands, the counts, the sample characters -
comes out of the live command table and the shipped roster.

Set INVITE below to your bot's own invite link. It cannot be discovered from
here: the bot builds it at runtime from its client id, which only Discord
knows.
"""
import argparse
import asyncio
import base64
import html
import io
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "site", "index.html")

# The bot's invite link, which is public — $invite prints it in Discord.
# --invite or YURI_INVITE overrides it.
INVITE = ("https://discord.com/oauth2/authorize"
          "?client_id=1550497695582519418&scope=bot&permissions=379904")

# How many characters the browser section carries. The whole roster is a
# hundred thousand; a page does not need that to make the point.
SHOWCASE = 240

# --embed inlines the art instead of linking it, for hosts whose content
# policy refuses images from elsewhere. Small and few, because every one of
# them is carried in the page itself.
EMBED_WIDTH = 190
EMBED_QUALITY = 74


async def collect():
    """Commands and categories, straight from the bot."""
    os.environ.setdefault("DISCORD_TOKEN", "unused-for-listing")
    sys.path.insert(0, ROOT)
    import tempfile
    import discord
    from discord.ext import commands as dcmd
    import db as dbmod
    import bot as botmod
    from cogs import help as helpmod

    client = dcmd.Bot(command_prefix="$", intents=discord.Intents.default())
    client.db = dbmod.Database(os.path.join(tempfile.mkdtemp(), "site.db"))
    client.remove_command("help")
    for cog in botmod.COGS:
        await client.load_extension(cog)

    sections = []
    for icon, name, entries in helpmod.CATEGORIES:
        items = []
        for command, blurb in entries:
            found = client.get_command(command)
            items.append({
                "name": command,
                "blurb": blurb,
                "help": (found.help or "").strip().split("\n")[0] if found else "",
                "aliases": sorted(found.aliases) if found else [],
            })
        sections.append({"icon": icon, "name": name, "items": items})

    total = len({c.qualified_name for c in client.walk_commands()})
    await client.close()
    return sections, total


def characters():
    """A sample of the roster, best first, for the browser section."""
    sys.path.insert(0, ROOT)
    import utils

    rows = list(utils.iter_roster(os.path.join(ROOT, "data", "characters.json")))
    total = len(rows)
    series = len({r["series"] for r in rows})
    rows.sort(key=lambda r: r["claim_rank"])
    shown = [
        {
            "n": r["name"],
            "s": r["series"],
            "k": r["base_karuda"],
            "r": r["claim_rank"],
            "g": (r.get("gender") or "")[:1],
            "i": r["image_url"],
        }
        for r in rows
        # Only linkable art: the bundled files live with the bot, not here.
        if str(r.get("image_url", "")).startswith("https://")
    ][:SHOWCASE]
    return shown, total, series


def inline(url: str) -> str:
    """One portrait as a data URI, shrunk so the page stays a page."""
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; gachabot-site/1.0)",
        "Accept": "image/*,*/*",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()

    try:
        from PIL import Image
    except ImportError:
        return "data:image/jpeg;base64," + base64.b64encode(raw).decode()

    image = Image.open(io.BytesIO(raw))
    image.load()
    if image.mode != "RGB":
        image = image.convert("RGB")
    if image.width > EMBED_WIDTH:
        height = round(image.height * EMBED_WIDTH / image.width)
        image = image.resize((EMBED_WIDTH, height), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=EMBED_QUALITY, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


PAGE = r"""<title>Yuri Gacha</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700&family=Zen+Kaku+Gothic+New:wght@400;500;700&family=JetBrains+Mono:wght@500&display=swap">
<style>
:root{
  --ink:#0D0B14; --panel:#171324; --raise:#1F1A30; --line:#2C2444;
  --text:#ECE8F7; --dim:#948CAE; --faint:#6B6484;
  --accent:#7C6BF0; --accent-soft:#9C8FF5; --gold:#E5C55A; --rose:#EE7FA8;
  --ok:#43B581;
  --display:"Sora","Segoe UI",system-ui,sans-serif;
  --body:"Zen Kaku Gothic New","Hiragino Sans","Segoe UI",system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,"SF Mono",Menlo,monospace;
}
*{box-sizing:border-box}
body{
  margin:0;background:var(--ink);color:var(--text);
  font-family:var(--body);font-size:16px;line-height:1.6;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1120px;margin:0 auto;padding-inline:20px}
a{color:var(--accent-soft);text-decoration:none}
a:hover{text-decoration:underline}
:focus-visible{outline:2px solid var(--accent-soft);outline-offset:3px;border-radius:4px}

/* ---- nav ---- */
nav{
  position:sticky;top:env(safe-area-inset-top,0px);z-index:50;
  background:rgba(13,11,20,.86);backdrop-filter:blur(12px);
  border-bottom:1px solid var(--line);
}
.nav-in{display:flex;align-items:center;gap:22px;height:58px}
.brand{
  font-family:var(--display);font-weight:700;font-size:18px;letter-spacing:-.01em;
  color:var(--text);display:flex;align-items:center;gap:9px;margin-right:auto;
}
.brand span{
  width:22px;height:22px;border-radius:7px;display:grid;place-items:center;
  background:linear-gradient(140deg,var(--accent),var(--rose));
  font-size:12px;color:#0D0B14;font-weight:700;
}
.nav-in a.link{color:var(--dim);font-size:14px;font-weight:500}
.nav-in a.link:hover{color:var(--text);text-decoration:none}
@media(max-width:700px){.nav-in a.link{display:none}}

/* ---- hero ---- */
header{padding-block:64px 44px;border-bottom:1px solid var(--line)}
.eyebrow{
  font-family:var(--mono);font-size:12px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--accent-soft);margin:0 0 14px;
}
h1{
  font-family:var(--display);font-weight:700;letter-spacing:-.03em;
  font-size:clamp(34px,6vw,58px);line-height:1.04;margin:0 0 18px;
  text-wrap:balance;
}
h1 em{font-style:normal;color:var(--accent-soft)}
.lede{font-size:clamp(16px,2vw,19px);color:var(--dim);max-width:60ch;margin:0}
.cta{display:flex;flex-wrap:wrap;gap:12px;margin-top:28px}
.btn{
  font-family:var(--display);font-weight:600;font-size:15px;
  padding:11px 20px;border-radius:10px;border:1px solid transparent;
  background:var(--accent);color:#0C0A14;display:inline-block;
}
.btn:hover{background:var(--accent-soft);text-decoration:none}
.btn.ghost{background:transparent;border-color:var(--line);color:var(--text)}
.btn.ghost:hover{border-color:var(--accent);background:var(--raise)}

.stats{display:flex;flex-wrap:wrap;gap:34px;margin-top:40px}
.stat b{
  display:block;font-family:var(--display);font-weight:700;
  font-size:30px;letter-spacing:-.02em;font-variant-numeric:tabular-nums;
}
.stat i{font-style:normal;font-size:13px;color:var(--faint);
  font-family:var(--mono);letter-spacing:.06em;text-transform:uppercase}

/* ---- sections ---- */
section{padding-block:60px;border-bottom:1px solid var(--line)}
h2{
  font-family:var(--display);font-weight:600;letter-spacing:-.02em;
  font-size:clamp(23px,3vw,30px);margin:0 0 8px;text-wrap:balance;
}
.sub{color:var(--dim);margin:0 0 30px;max-width:62ch}

/* ---- setup: a real sequence, so it is numbered ---- */
.steps{display:grid;gap:16px}
.step{
  display:grid;grid-template-columns:44px 1fr;gap:18px;align-items:start;
  background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:20px 22px;
}
.step .num{
  font-family:var(--mono);font-size:13px;color:var(--accent-soft);
  background:var(--raise);border:1px solid var(--line);border-radius:9px;
  width:36px;height:36px;display:grid;place-items:center;
}
.step h3{font-family:var(--display);font-weight:600;font-size:17px;margin:4px 0 6px}
.step p{margin:0 0 10px;color:var(--dim);font-size:15px}
.step p:last-child{margin-bottom:0}
code,kbd{
  font-family:var(--mono);font-size:13.5px;
  background:var(--raise);border:1px solid var(--line);
  padding:2px 7px;border-radius:6px;color:var(--gold);white-space:nowrap;
}
.cmdline{
  display:block;background:#0A0812;border:1px solid var(--line);
  border-radius:10px;padding:12px 15px;color:var(--gold);
  font-family:var(--mono);font-size:14px;overflow-x:auto;white-space:pre;
}
.note{
  border-left:2px solid var(--accent);padding-left:14px;color:var(--dim);
  font-size:14.5px;margin-top:12px;
}

/* ---- commands ---- */
.tools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:22px}
#q{
  flex:1 1 260px;background:var(--panel);border:1px solid var(--line);
  border-radius:10px;padding:11px 14px;color:var(--text);
  font-family:var(--body);font-size:15px;
}
#q::placeholder{color:var(--faint)}
.chip{
  font-family:var(--mono);font-size:12px;letter-spacing:.03em;
  background:var(--panel);border:1px solid var(--line);color:var(--dim);
  padding:7px 12px;border-radius:999px;cursor:pointer;
}
.chip[aria-pressed="true"]{
  background:var(--accent);border-color:var(--accent);color:#0C0A14;font-weight:600;
}
.group{margin-bottom:34px}
.group h3{
  font-family:var(--display);font-weight:600;font-size:15px;letter-spacing:.02em;
  margin:0 0 12px;display:flex;align-items:center;gap:9px;color:var(--text);
}
.group h3 b{
  font-family:var(--mono);font-weight:500;font-size:11px;color:var(--faint);
  border:1px solid var(--line);border-radius:999px;padding:2px 8px;
}
.cmds{display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(270px,1fr))}
.cmd{
  background:var(--panel);border:1px solid var(--line);border-radius:11px;
  padding:12px 14px;
}
.cmd .n{font-family:var(--mono);font-size:14px;color:var(--accent-soft);font-weight:500}
.cmd .b{display:block;font-size:14px;color:var(--dim);margin-top:3px}
.cmd .a{
  display:block;font-family:var(--mono);font-size:11.5px;color:var(--faint);
  margin-top:6px;overflow-wrap:anywhere;
}
#empty{color:var(--dim);display:none}

/* ---- characters ---- */
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(146px,1fr))}
.card{
  background:var(--panel);border:1px solid var(--line);border-radius:12px;
  overflow:hidden;display:flex;flex-direction:column;
}
.card .art{
  aspect-ratio:3/4;max-width:100%;width:100%;object-fit:cover;
  background:var(--raise);display:block;
}
.card .meta{padding:9px 11px 11px}
.card .nm{
  font-family:var(--display);font-weight:600;font-size:13.5px;line-height:1.3;
  display:block;overflow-wrap:anywhere;
}
.card .sr{font-size:11.5px;color:var(--faint);display:block;margin-top:2px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card .kr{
  font-family:var(--mono);font-size:11.5px;color:var(--gold);margin-top:7px;
  display:flex;justify-content:space-between;font-variant-numeric:tabular-nums;
}
.card .kr span{color:var(--faint)}

footer{padding-block:38px 56px;color:var(--faint);font-size:13.5px}
footer p{margin:0 0 6px}
</style>
</head>
<body>

<nav><div class="wrap nav-in">
  <a class="brand" href="#top"><span>Y</span>Yuri</a>
  <a class="link" href="#setup">Setup</a>
  <a class="link" href="#commands">Commands</a>
  <a class="link" href="#characters">Characters</a>
</div></nav>

<div id="top" class="wrap">
<header>
  <p class="eyebrow">Discord gacha</p>
  <h1>Roll for <em>__TOTAL__</em> characters.<br>Claim the ones worth keeping.</h1>
  <p class="lede">A gacha bot in the shape of Mudae, with its own roster and its
  own currency. Every character is ranked on how many people have actually
  favourited them — what somebody is worth is measured, not guessed.</p>
  <div class="cta">
    __INVITE__
    <a class="btn ghost" href="#setup">Set it up</a>
  </div>
  <div class="stats">
    <div class="stat"><b>__TOTAL__</b><i>characters</i></div>
    <div class="stat"><b>__SERIES__</b><i>series</i></div>
    <div class="stat"><b>__COMMANDS__</b><i>commands</i></div>
    <div class="stat"><b>__STEPS__</b><i>tutorial steps</i></div>
  </div>
</header>

<section id="setup">
  <h2>Getting it working on your server</h2>
  <p class="sub">Six steps, in order. The first two matter most — everything
  after them is taste.</p>
  <div class="steps">__STEPS_HTML__</div>
</section>

<section id="commands">
  <h2>Every command</h2>
  <p class="sub">__COMMANDS__ of them. Type <code>$help</code> in Discord and
  the same list arrives by DM.</p>
  <div class="tools">
    <input id="q" type="search" placeholder="Search commands, or what they do…"
           autocomplete="off" aria-label="Search commands">
    <button class="chip" id="all" aria-pressed="true">All</button>
  </div>
  <div id="groups">__COMMANDS_HTML__</div>
  <p id="empty">Nothing matches that.</p>
</section>

<section id="characters">
  <h2>The top of the roster</h2>
  <p class="sub">The __SHOWN__ most wanted, out of __TOTAL__. Value comes from
  how much people want to own somebody, which is not the same as how many have
  heard of them — so the top here is not the top of a popularity chart.</p>
  <div class="grid">__CHARACTERS_HTML__</div>
</section>

<footer>
  <p>Yuri runs on its own roster built from AniList, plus games and cartoons
  AniList does not carry.</p>
  <p>Character art belongs to its creators and is shown here for
  identification.</p>
</footer>
</div>

<script>
(function(){
  var q = document.getElementById("q");
  var all = document.getElementById("all");
  var empty = document.getElementById("empty");
  var groups = Array.prototype.slice.call(
    document.querySelectorAll("#groups .group"));

  function apply(){
    var needle = q.value.trim().toLowerCase();
    var anything = false;
    groups.forEach(function(group){
      var shown = 0;
      Array.prototype.forEach.call(group.querySelectorAll(".cmd"), function(cmd){
        var hit = !needle || cmd.dataset.find.indexOf(needle) !== -1;
        cmd.hidden = !hit;
        if (hit) shown++;
      });
      group.hidden = shown === 0;
      if (shown) anything = true;
      var count = group.querySelector("h3 b");
      if (count) count.textContent = shown;
    });
    empty.style.display = anything ? "none" : "block";
  }

  q.addEventListener("input", apply);
  all.addEventListener("click", function(){ q.value = ""; apply(); q.focus(); });
  apply();
})();
</script>
"""


def step_html(steps) -> str:
    out = []
    for number, (title, body) in enumerate(steps, 1):
        out.append(
            f'<div class="step"><div class="num">{number:02d}</div>'
            f'<div><h3>{title}</h3>{body}</div></div>'
        )
    return "\n".join(out)


# The page body is authored for the artifact publisher, which wraps it in a
# head of its own. Hosted anywhere else there is no wrapper, so the generator
# emits a whole document: without the charset every em dash and Japanese name
# arrives as mojibake, and without the viewport a phone renders the page at
# desktop width and zooms out.
DOCUMENT = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="Yuri is a Discord gacha bot: roll for characters, claim them, keep them. Every command, and how to set it up in your server.">
<meta name="color-scheme" content="dark">
<meta property="og:title" content="Yuri Gacha">
<meta property="og:description" content="Roll for characters, claim them, keep them. Every command, and how to set the bot up in your server.">
<meta property="og:type" content="website">
__PAGE__
</body>
</html>
"""


def build(embed: int = 0, invite_url: str = ""):
    sections, command_total = asyncio.run(collect())
    shown, total, series = characters()

    if embed:
        shown = shown[:embed]
        kept = []
        for row in shown:
            try:
                row["i"] = inline(row["i"])
                kept.append(row)
            except Exception as error:  # noqa: BLE001 - one bad portrait
                print(f"  skipped {row['n']}: {type(error).__name__}")
        shown = kept
        print(f"  inlined {len(shown)} portraits")

    sys.path.insert(0, ROOT)
    import tutorial

    esc = html.escape
    steps = [
        ("Add the bot", """
         <p>Run <code>$invite</code> in a server that already has it, or use
         the button at the top of this page. It asks for permission to send
         messages, embed links and attach files — nothing else.</p>"""),
        ("Give it one channel", """
         <p>Left alone the bot answers everywhere, which gets old fast in a
         busy server.</p>
         <code class="cmdline">$channelallow #bot-chat</code>
         <p class="note"><code>$channellist</code> shows which channels are
         allowed, and <code>$channelclear</code> lets it answer everywhere
         again.</p>"""),
        ("Stop commands in other channels", """
         <p>The step above makes the bot <em>ignore</em> commands elsewhere;
         the message still sits there. A Discord AutoMod rule deletes it.</p>
         <p>Server Settings → AutoMod → Create your own → Custom Keywords →
         Block Message, and exempt your bot channel. The command list to paste
         is generated by the bot's own tooling, so it never goes stale.</p>"""),
        ("Pick a pace", """
         <p>One command sets five dials at once, so nobody has to learn the
         settings table on day one.</p>
         <code class="cmdline">$preset relaxed &nbsp;·&nbsp; $preset normal
&nbsp;·&nbsp; $preset slow</code>
         <p class="note"><code>$settings</code> shows every dial afterwards,
         and <code>$set &lt;key&gt; &lt;value&gt;</code> changes one.</p>"""),
        ("Decide what can roll", """
         <p>The roster carries games and Western cartoons as well as anime.
         A server that only wants anime can say so.</p>
         <code class="cmdline">$togglegames &nbsp;·&nbsp; $togglewestern</code>
         <p class="note"><code>$toggles</code> lists every switch and where it
         stands. They are all reversible.</p>"""),
        ("Point people at the tutorial", """
         <p><code>$tuto</code> walks a new player through the bot in
         """ + str(tutorial.MAIN_STEPS) + """ steps and pays them for
         finishing each one. They learn the commands by using them rather
         than by reading a list.</p>"""),
    ]

    groups = []
    for section in sections:
        cards = []
        for item in section["items"]:
            find = " ".join([item["name"], item["blurb"], item["help"],
                             " ".join(item["aliases"])]).lower()
            aliases = (f'<span class="a">also: '
                       + " ".join("$" + esc(a) for a in item["aliases"][:6])
                       + "</span>") if item["aliases"] else ""
            cards.append(
                f'<div class="cmd" data-find="{esc(find)}">'
                f'<span class="n">${esc(item["name"])}</span>'
                f'<span class="b">{esc(item["blurb"])}</span>{aliases}</div>'
            )
        groups.append(
            f'<div class="group"><h3>{section["icon"]} {esc(section["name"])}'
            f'<b>{len(cards)}</b></h3>'
            f'<div class="cmds">{"".join(cards)}</div></div>'
        )

    cards = []
    for row in shown:
        mark = {"F": "♀", "M": "♂"}.get(row["g"], "")
        cards.append(
            f'<div class="card">'
            f'<img class="art" loading="lazy" alt="{esc(row["n"])}"'
            f' src="{esc(row["i"])}">'
            f'<div class="meta"><span class="nm">{esc(row["n"])}</span>'
            f'<span class="sr">{esc(row["s"])}</span>'
            f'<span class="kr">{row["k"]:,} karuda'
            f'<span>#{row["r"]:,} {mark}</span></span></div></div>'
        )

    link = invite_url or INVITE
    invite = (f'<a class="btn" href="{esc(link)}">Add Yuri to your server</a>'
              if link else
              '<a class="btn ghost" href="#setup">Run $invite for the link</a>')

    page = (PAGE
            .replace("__TOTAL__", f"{total:,}")
            .replace("__SERIES__", f"{series:,}")
            .replace("__COMMANDS__", f"{command_total:,}")
            .replace("__STEPS__", str(tutorial.TOTAL_STEPS))
            .replace("__SHOWN__", f"{len(shown):,}")
            .replace("__INVITE__", invite)
            .replace("__STEPS_HTML__", step_html(steps))
            .replace("__COMMANDS_HTML__", "\n".join(groups))
            .replace("__CHARACTERS_HTML__", "\n".join(cards)))
    page = DOCUMENT.replace("__PAGE__", page)
    return page, total, series, command_total, len(shown)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=OUT)
    parser.add_argument("--embed", type=int, default=0, metavar="N",
                        help="inline this many portraits as data URIs, for"
                             " hosts that block images from elsewhere")
    parser.add_argument("--invite", default=os.getenv("YURI_INVITE", ""),
                        metavar="URL",
                        help="the bot's invite link, for the hero button;"
                             " $invite prints it in Discord")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    page, total, series, commands, shown = build(args.embed, args.invite)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(page)

    print(f"{commands} commands · {total:,} characters · {series:,} series")
    print(f"  showcase: {shown} characters"
          + (" (art inlined)" if args.embed else " with linkable art"))
    print(f"  page: {len(page) / 1024:.0f} KB")
    if not (args.invite or INVITE):
        print("  no invite link - the button points at the setup section;"
              " pass --invite URL")
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
