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
# Original characters for the Secret button. tools/add_secret.py writes both
# this file and the images it points at, under site/secret/.
SECRET_DATA = os.path.join(ROOT, "data", "secret_characters.json")

# The bot's application id, which is public: it is in every invite link.
# The permissions come from cogs/profile.py, the same list $invite uses.
# --invite or YURI_INVITE overrides the whole link.
CLIENT_ID = 1550497695582519418

# The three parts of the bot, each with its own tab on the page. Sections
# are named as they are in cogs/help.py; anything not listed is the gacha.
# build() fails loudly if a name here stops matching, so renaming a help
# section can't quietly move it to the wrong tab.
AREAS = (
    ("gacha", "Gacha"),
    ("mod", "Moderation"),
    ("voice", "Voice"),
    ("levels", "Levels"),
)
AREA_OF = {
    "Jail & mutes": "mod", "Warnings": "mod", "Kicks & bans": "mod",
    "Cleaning up": "mod", "Records & names": "mod", "Mod setup": "mod",
    "Staff points": "mod",
    "Voice rooms": "voice", "Voice hours": "voice",
    "Levels": "levels", "Level setup": "levels",
}

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

    from cogs.profile import INVITE_PERMISSIONS

    names = {name for _icon, name, _entries in helpmod.CATEGORIES}
    stale = sorted(set(AREA_OF) - names)
    if stale:
        raise SystemExit("AREA_OF names help sections that no longer exist: "
                         + ", ".join(stale))
    invite = discord.utils.oauth_url(CLIENT_ID, permissions=INVITE_PERMISSIONS,
                                     scopes=("bot",))

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
        sections.append({"icon": icon, "name": name, "items": items,
                         "area": AREA_OF.get(name, "gacha")})

    total = len({c.qualified_name for c in client.walk_commands()})
    await client.close()
    return sections, total, invite


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
/* The hidden attribute loses to any display rule - .grid's display:grid
   kept the roster on screen under the Secret tab - so it has to win. */
[hidden]{display:none!important}
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
/* Without this a grid column is as wide as its longest command line, and
   on a phone that pushes the whole card off the side of the screen. */
.step>div{min-width:0}
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
.group{scroll-margin-top:80px}

/* ---- tabs: one per part of the bot, shared by setup and commands ---- */
.tabs{display:flex;flex-wrap:wrap;gap:8px}
.tabs .chip{font-size:13px;padding:8px 16px}
.jump{display:flex;flex-wrap:wrap;gap:6px 14px;margin:0 0 28px;
  padding:12px 16px;background:var(--panel);border:1px solid var(--line);
  border-radius:12px;font-size:13.5px}
.jump a{color:var(--dim);white-space:nowrap}
.jump a:hover{color:var(--text)}
.setup-tabs{margin-bottom:22px}

/* ---- features: the three parts at a glance ---- */
.features{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.feature{background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:22px;display:flex;flex-direction:column}
.feature .ic{font-size:22px;line-height:1;margin-bottom:12px}
.feature h3{font-family:var(--display);font-weight:600;font-size:19px;margin:0 0 6px}
.feature p{color:var(--dim);font-size:15px;margin:0 0 12px}
.feature ul{margin:0 0 18px;padding-left:18px;color:var(--dim);font-size:14.5px}
.feature li{margin-bottom:3px}
.feature .go{margin-top:auto;display:flex;gap:16px;font-size:14px;font-weight:500}

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

/* ---- secret: original characters, one album each ---- */
.sec-row{display:flex;flex-wrap:wrap;align-items:flex-start;
  justify-content:space-between;gap:4px 28px}
.secret-toggle{margin-top:4px;cursor:pointer;border-color:var(--rose);
  color:var(--rose);flex:none}
.secret-toggle:hover{background:var(--raise);border-color:var(--rose)}
.secret-toggle[aria-pressed="true"]{background:var(--rose);color:#0C0A14}
button.card{font:inherit;color:inherit;text-align:left;padding:0;
  cursor:pointer;width:100%}
button.card:hover{border-color:var(--rose)}
.card .kr.tag{color:var(--rose)}
/* White behind secret art: transparent emotes drawn with black outlines
   disappear into a dark card. */
.secret-card .art,#album-img{background:#fff}
.secret-card .art{object-fit:contain}

#album{background:var(--panel);color:var(--text);border:1px solid var(--line);
  border-radius:14px;padding:14px;width:min(92vw,760px);max-width:92vw}
#album::backdrop{background:rgba(6,5,10,.84)}
.album-top{display:flex;align-items:center;gap:12px;margin-bottom:10px;
  font-family:var(--display);font-weight:600}
#album-count{font-family:var(--mono);font-size:12px;color:var(--faint);
  margin-left:auto;font-variant-numeric:tabular-nums}
#album-img{display:block;max-width:100%;max-height:72vh;margin:0 auto;
  border-radius:8px;object-fit:contain}
.album-nav{display:flex;justify-content:center;gap:10px;margin-top:12px}
#album button{font:inherit;background:var(--raise);color:var(--text);
  border:1px solid var(--line);border-radius:9px;padding:8px 18px;cursor:pointer}
#album button:disabled{opacity:.35;cursor:default}
#album button:hover:not(:disabled){border-color:var(--rose)}

footer{padding-block:38px 56px;color:var(--faint);font-size:13.5px}
footer p{margin:0 0 6px}
</style>
</head>
<body>

<nav><div class="wrap nav-in">
  <a class="brand" href="#top"><span>Y</span>Yuri</a>
  <a class="link" href="#features">Features</a>
  <a class="link" href="#setup">Setup</a>
  <a class="link" href="#commands">Commands</a>
  <a class="link" href="#characters">Characters</a>
</div></nav>

<div id="top" class="wrap">
<header>
  <p class="eyebrow">Gacha · Moderation · Voice · Levels</p>
  <h1>Roll for <em>__TOTAL__</em> characters.<br>Run the server too.</h1>
  <p class="lede">A gacha bot in the shape of Mudae, with its own roster and
  currency, plus the moderation, voice rooms and levels a server needs, so
  one bot does the job of four.</p>
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

<section id="features">
  <h2>What it does</h2>
  <p class="sub">Four parts. Use all of them, or only the ones you need.</p>
  <div class="features">__FEATURES_HTML__</div>
</section>

<section id="setup">
  <h2>Getting it working on your server</h2>
  <p class="sub">Pick the part you're setting up. The steps are in order.</p>
  <div class="tabs setup-tabs" role="group" aria-label="Part of the bot">__TABS_HTML__</div>
  __SETUP_HTML__
</section>

<section id="commands">
  <h2>Every command</h2>
  <p class="sub">__COMMANDS__ of them, split by what they're for. Search looks
  through all of them. Type <code>$help</code> in Discord and the same list
  arrives by DM.</p>
  <div class="tools">
    <input id="q" type="search" placeholder="Search every command, or what it does…"
           autocomplete="off" aria-label="Search commands">
    <div class="tabs" role="group" aria-label="Part of the bot">__TABS_HTML__</div>
  </div>
  __JUMP_HTML__
  <div id="groups">__COMMANDS_HTML__</div>
  <p id="empty">Nothing matches that.</p>
</section>

<section id="characters">
  <div class="sec-row">
    <div>
      <h2 id="roster-title">The top of the roster</h2>
      <p class="sub" id="roster-sub">The __SHOWN__ most wanted, out of __TOTAL__.
      Value comes from how much people want to own somebody, which is not the
      same as how many have heard of them — so the top here is not the top of
      a popularity chart.</p>
      <p class="sub" id="secret-sub" hidden>Original characters from the
      people around Yuri. Tap one to flip through their art.</p>
    </div>
    __SECRET_BUTTON__
  </div>
  <div class="grid" id="roster-grid">__CHARACTERS_HTML__</div>
  __SECRET_HTML__
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
  // One part of the bot at a time, picked by the tabs in Setup and in
  // Commands (they move together). Typing a search looks through every part.
  var q = document.getElementById("q");
  var empty = document.getElementById("empty");
  var groups = Array.prototype.slice.call(
    document.querySelectorAll("#groups .group"));
  var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-tab]"));
  var panels = Array.prototype.slice.call(document.querySelectorAll("[data-panel]"));
  var jumps = Array.prototype.slice.call(document.querySelectorAll(".jump"));
  var area = "gacha";

  function apply(){
    var needle = q.value.trim().toLowerCase();
    var anything = false;
    groups.forEach(function(group){
      var mine = needle ? true : group.dataset.area === area;
      var shown = 0;
      Array.prototype.forEach.call(group.querySelectorAll(".cmd"), function(cmd){
        var hit = !needle || cmd.dataset.find.indexOf(needle) !== -1;
        cmd.hidden = !hit;
        if (hit) shown++;
      });
      group.hidden = !mine || shown === 0;
      if (!group.hidden) anything = true;
      var count = group.querySelector("h3 b");
      if (count) count.textContent = shown;
    });
    jumps.forEach(function(jump){
      jump.hidden = !!needle || jump.dataset.area !== area;
    });
    tabs.forEach(function(tab){
      var on = tab.dataset.tab === area;
      // In Commands, a search shows every part, so no tab is lit.
      var inCommands = !!tab.closest("#commands");
      tab.setAttribute("aria-pressed", on && !(inCommands && needle) ? "true" : "false");
    });
    panels.forEach(function(panel){ panel.hidden = panel.dataset.panel !== area; });
    empty.style.display = anything ? "none" : "block";
  }

  function choose(next){
    area = next;
    q.value = "";
    apply();
  }

  tabs.forEach(function(tab){
    tab.addEventListener("click", function(){ choose(tab.dataset.tab); });
  });
  q.addEventListener("input", apply);

  // Links like #commands-mod or #setup-voice open that part's tab.
  function fromHash(){
    var match = /^#(setup|commands)-(\w+)$/.exec(location.hash);
    if (!match || !document.querySelector('[data-tab="' + match[2] + '"]')) return;
    choose(match[2]);
    document.getElementById(match[1]).scrollIntoView();
  }
  window.addEventListener("hashchange", fromHash);
  apply();
  fromHash();
})();

(function(){
  var toggle = document.getElementById("secret-toggle");
  if (!toggle) return;
  var roster = document.getElementById("roster-grid");
  var secret = document.getElementById("secret");
  var title = document.getElementById("roster-title");
  var rosterSub = document.getElementById("roster-sub");
  var secretSub = document.getElementById("secret-sub");
  var dialog = document.getElementById("album");
  var img = document.getElementById("album-img");
  var count = document.getElementById("album-count");
  var label = document.getElementById("album-name");
  var prev = dialog.querySelector(".prev");
  var next = dialog.querySelector(".next");
  var album = [], at = 0;

  function show(on){
    roster.hidden = on;
    secret.hidden = !on;
    rosterSub.hidden = on;
    secretSub.hidden = !on;
    title.textContent = on ? "Secret" : "The top of the roster";
    toggle.textContent = on ? "Back to the roster" : "Secret";
    toggle.setAttribute("aria-pressed", on ? "true" : "false");
  }

  toggle.addEventListener("click", function(){
    var on = secret.hidden;
    show(on);
    try { history.replaceState(null, "", on ? "#secret" : "#characters"); }
    catch (e) {}
  });

  function paint(){
    img.src = album[at];
    img.alt = label.textContent + ", image " + (at + 1) + " of " + album.length;
    count.textContent = (at + 1) + " / " + album.length;
    prev.disabled = at === 0;
    next.disabled = at === album.length - 1;
  }
  function step(by){
    at = Math.max(0, Math.min(album.length - 1, at + by));
    paint();
  }

  Array.prototype.forEach.call(document.querySelectorAll(".secret-card"),
    function(card){
      card.addEventListener("click", function(){
        album = JSON.parse(card.dataset.album);
        at = 0;
        label.textContent = card.dataset.name;
        paint();
        if (dialog.showModal) dialog.showModal();
        else dialog.setAttribute("open", "");
      });
    });

  prev.addEventListener("click", function(){ step(-1); });
  next.addEventListener("click", function(){ step(1); });
  dialog.querySelector(".close").addEventListener("click", function(){
    dialog.close();
  });
  // A click on the dimmed backdrop lands on the dialog itself.
  dialog.addEventListener("click", function(event){
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener("keydown", function(event){
    if (event.key === "ArrowLeft") step(-1);
    if (event.key === "ArrowRight") step(1);
  });

  // A shared link to #secret opens straight onto it.
  if (location.hash === "#secret") {
    show(true);
    document.getElementById("characters").scrollIntoView();
  }
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


def secret_markup() -> tuple:
    """The Secret button and everything behind it: (button, grid + viewer).

    Both come back empty when there are no secret characters, so the page
    carries no button that opens onto nothing.
    """
    import json

    esc = html.escape
    if not os.path.exists(SECRET_DATA):
        return "", ""
    with io.open(SECRET_DATA, encoding="utf-8") as handle:
        people = [c for c in json.load(handle).get("characters", [])
                  if c.get("images")]
    if not people:
        return "", ""

    cards = []
    for person in people:
        images = person["images"]
        count = f"{len(images)} image" + ("" if len(images) == 1 else "s")
        # A rollable one shows what it is worth and how rare it is; the rest
        # are only here to be looked at.
        if person.get("rollable"):
            tag = (f'{person.get("value", 0):,} karuda'
                   f'<span>1 in {person.get("odds", 0):,}</span>')
        else:
            tag = f"Secret<span>{count}</span>"
        cards.append(
            f'<button type="button" class="card secret-card"'
            f' data-name="{esc(person["name"])}"'
            f' data-album="{esc(json.dumps(images))}">'
            f'<img class="art" loading="lazy" alt="{esc(person["name"])}"'
            f' src="{esc(images[0])}">'
            f'<div class="meta"><span class="nm">{esc(person["name"])}</span>'
            f'<span class="sr">{esc(person.get("by") or "Original character")}'
            f'</span><span class="kr tag">{tag}</span>'
            f'</div></button>'
        )

    button = ('<button type="button" class="btn ghost secret-toggle"'
              ' id="secret-toggle" aria-pressed="false"'
              ' aria-controls="secret">Secret</button>')
    body = (
        f'<div id="secret" hidden><div class="grid">{"".join(cards)}</div></div>'
        '<dialog id="album" aria-label="Album">'
        '<div class="album-top"><span id="album-name"></span>'
        '<span id="album-count"></span>'
        '<button type="button" class="close" aria-label="Close">✕</button>'
        '</div><img id="album-img" alt="">'
        '<div class="album-nav">'
        '<button type="button" class="prev" aria-label="Previous image">◀</button>'
        '<button type="button" class="next" aria-label="Next image">▶</button>'
        '</div></dialog>'
    )
    return button, body


def build(embed: int = 0, invite_url: str = ""):
    sections, command_total, bot_invite = asyncio.run(collect())
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
    gacha_steps = [
        ("Add the bot", """
         <p>Run <code>$invite</code> in a server that already has it, or use
         the button at the top of this page. It asks for what all three parts
         need: messages and embeds for the gacha, roles, kicks, bans and
         timeouts for moderation, and moving members for voice. Untick
         anything for a part you won't use.</p>"""),
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
    mod_steps = [
        ("Put the bot above your staff", """
         <p>Server Settings → Roles: drag the bot's role above your staff
         roles. It can only jail, mute or ban people whose top role is below
         its own.</p>"""),
        ("Give your staff their permissions", """
         <p>The bot follows Discord's own permissions, so staff ranks are
         just roles.</p>
         <p><b>Trial Mods</b> need <code>Timeout Members</code>: jail,
         timeouts, mutes and warnings.<br><b>Mods</b> also need
         <code>Kick Members</code> and <code>Ban Members</code>.</p>"""),
        ("Run setup", """
         <p>Name your staff roles and the bot makes everything else: Jailed,
         Image Muted and Reaction Muted roles, a <code>#jail</code> channel
         and a <code>#mod-logs</code> channel only staff can see.</p>
         <code class="cmdline">$setupmod @Mod @Trial Mod</code>"""),
        ("Choose what happens automatically", """
         <p>Optional. Punish people when they reach a number of warnings,
         and word the bot's messages your own way.</p>
         <code class="cmdline">$warnpunish add 3 timeout 1h
$invoke set jail message {user.mention} is in jail: {reason}</code>"""),
        ("Track who's ready for promotion", """
         <p>Every jail and mute gives the staff member who did it a point.
         Mods give points by hand for reports that end in a ban.</p>
         <code class="cmdline">$point @trialmod ban
$toppoints</code>
         <p class="note"><code>$modhistory @trialmod</code> counts every
         action someone has taken.</p>"""),
    ]
    voice_steps = [
        ("Make Join To Create", """
         <p>Makes a category with a <code>Join To Create</code> voice channel
         and a <code>#vc-info</code> channel with the commands in it. To use
         a voice channel you already have, give its id.</p>
         <code class="cmdline">$vc setup
$vc setup 123456789012345678</code>
         <p class="note">Only let one bot run Join To Create, or both will
         make a room every time someone joins.</p>"""),
        ("Let people run their rooms", """
         <p>Whoever joins gets their own channel, deleted when it empties.
         They lock it, hide it, rename it and choose who gets in, from the
         channel's own chat.</p>
         <code class="cmdline">$vc lock · $vc permit @friend · $vc rename chill</code>
         <p class="note"><code>$vc panel</code> posts the full command list
         anywhere.</p>"""),
        ("Reward time in voice", """
         <p>Every minute in voice is counted, except in the AFK channel.
         Hand out roles at milestones.</p>
         <code class="cmdline">$vc hours add 10 @Regular
$vc lb</code>"""),
    ]
    level_steps = [
        ("Nothing to switch on", """
         <p>Levels start counting the moment the bot is in your server.
         Chatting earns XP once a minute, and voice earns it too when
         there's someone to talk to.</p>
         <code class="cmdline">$rank · $levels</code>"""),
        ("Reward the milestones", """
         <p>Hand out roles at levels. Anyone already past a level gets the
         role with one command.</p>
         <code class="cmdline">$levels role add 10 @Active
$levels sync</code>"""),
        ("Change it on the web", """
         <p>Run <code>$dashboard</code> and the bot DMs you a private link to
         a dashboard: XP per message and per minute in voice, level roles,
         the level-up message and where it goes, and channels that earn
         nothing. The link works only for you, for an hour.</p>
         <p class="note">Every setting is a command too: <code>$levels
         settings</code> shows them all.</p>"""),
        ("Tidy it up", """
         <p>Choose where level-ups are announced, and keep spam or bot
         channels from earning XP.</p>
         <code class="cmdline">$levels channel #level-ups
$levels ignore #bot-spam</code>
         <p class="note">Every 5 levels pays a little karuda, 100 by
         default, and only once per milestone, so it never outpaces
         <code>$daily</code>. <code>$levels karuda 0</code> turns it
         off.</p>"""),
    ]
    steps_by_area = {"gacha": gacha_steps, "mod": mod_steps,
                     "voice": voice_steps, "levels": level_steps}
    labels = dict(AREAS)
    subs = {
        "gacha": "Six steps. The first two matter most, the rest is taste.",
        "mod": "Five steps. After the third, every command works.",
        "voice": "Three steps. The first one is all you need.",
        "levels": "It works out of the box. The rest is up to you.",
    }
    tabs_html = "".join(
        f'<button type="button" class="chip" data-tab="{key}"'
        f' aria-pressed="false">{label}</button>' for key, label in AREAS)
    setup_html = "\n".join(
        f'<div data-panel="{key}"><p class="sub">{subs[key]}</p>'
        f'<div class="steps">{step_html(steps_by_area[key])}</div></div>'
        for key, _label in AREAS)

    counts = {key: sum(len(sec["items"]) for sec in sections
                       if sec["area"] == key) for key, _ in AREAS}
    features = [
        ("gacha", "\U0001f3b2", "Gacha",
         f"Roll for {total:,} characters and claim the ones worth keeping.",
         ["Wishlists, likes, trades and gifts",
          "Karuda, a shop, badges and a tower",
          "A tutorial that pays people to learn"]),
        ("mod", "\U0001f6e1\ufe0f", "Moderation",
         "Talk first, then decide. Every action is saved as a numbered case.",
         ["Jail, timeouts, image and reaction mutes",
          "Warnings with automatic punishments",
          "Bans, hardbans, lockdowns and staff points"]),
        ("voice", "\U0001f50a", "Voice",
         "Rooms people make and run themselves, and hours spent in voice.",
         ["Join To Create, deleted when empty",
          "Lock, hide, rename, permit, ban, transfer",
          "Hour leaderboard and hour roles"]),
        ("levels", "\U0001f4c8", "Levels",
         "XP for chatting and for time in voice, with roles at milestones.",
         ["Rank cards and a leaderboard",
          "Spam-proof: one message a minute counts",
          "A little karuda every 5 levels"]),
    ]
    features_html = "\n".join(
        f'<div class="feature"><div class="ic">{icon}</div><h3>{name}</h3>'
        f'<p>{esc(blurb)}</p><ul>{"".join(f"<li>{esc(x)}</li>" for x in points)}</ul>'
        f'<div class="go"><a href="#setup-{key}">Set it up</a>'
        f'<a href="#commands-{key}">{counts[key]} commands</a></div></div>'
        for key, icon, name, blurb, points in features)

    def slug(name):
        return "g-" + "".join(c if c.isalnum() else "-" for c in name.lower())

    jump_html = "\n".join(
        f'<nav class="jump" data-area="{key}" aria-label="{label} sections">'
        + "".join(f'<a href="#{slug(sec["name"])}">{esc(sec["name"])}</a>'
                  for sec in sections if sec["area"] == key)
        + "</nav>" for key, label in AREAS)

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
            f'<div class="group" id="{slug(section["name"])}"'
            f' data-area="{section["area"]}">'
            f'<h3>{section["icon"]} {esc(section["name"])}'
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

    secret_button, secret_html = secret_markup()

    link = invite_url or bot_invite
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
            .replace("__FEATURES_HTML__", features_html)
            .replace("__TABS_HTML__", tabs_html)
            .replace("__SETUP_HTML__", setup_html)
            .replace("__JUMP_HTML__", jump_html)
            .replace("__COMMANDS_HTML__", "\n".join(groups))
            .replace("__CHARACTERS_HTML__", "\n".join(cards))
            .replace("__SECRET_BUTTON__", secret_button)
            .replace("__SECRET_HTML__", secret_html))
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
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
