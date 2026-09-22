"""Fails if the built page is missing something invisible until it is read.

    python tools/check_site.py

The page once shipped with no <meta charset>, which is not the kind of bug a
build notices: nothing errors, the file is the right size, and every em dash
and Japanese name renders as mojibake for every visitor. Same for the viewport
tag, whose absence only shows on a phone.

CI runs this between building the page and deploying it, so a page that fails
here never replaces the one already live.
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "site", "index.html")

# Each of these must appear exactly once: twice means the document got
# wrapped twice, none means it was never wrapped at all.
ONCE = (
    "<!doctype html>",
    '<meta charset="utf-8">',
    'name="viewport"',
    "<body>",
    "</body>",
    "</html>",
)

MIN_BYTES = 80_000


def main():
    if not os.path.exists(PAGE):
        print(f"no page at {PAGE} - did the build run?")
        return 1

    page = io.open(PAGE, encoding="utf-8").read()
    problems = []

    for needed in ONCE:
        found = page.count(needed)
        if found != 1:
            problems.append(f"{needed!r} appears {found} times, wanted exactly 1")

    # The page toggles sections with the hidden attribute, which any display
    # rule overrides. Without this the Secret tab showed the whole roster.
    if "[hidden]{display:none!important}" not in page:
        problems.append("no [hidden]{display:none!important} rule, so hidden"
                        " sections with a display style stay on screen")

    head = page.split("<style>")[0]
    if "__" in head:
        problems.append("an unfilled __PLACEHOLDER__ reached the head")

    if len(page) < MIN_BYTES:
        problems.append(f"page is {len(page):,} bytes, expected at least"
                        f" {MIN_BYTES:,} - the roster probably did not load")

    # Mojibake reaching the file itself, rather than the browser guessing it.
    if "â€" in page or "Ã©" in page:
        problems.append("the page contains mojibake, so something decoded"
                        " UTF-8 as Latin-1 on the way in")

    if problems:
        print("the built page is not fit to ship:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"page looks sound: {len(page) / 1024:.0f} KB, all tags present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
