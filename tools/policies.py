"""The Privacy Policy and Terms of Service pages, for tools/build_site.py.

Written from what the bot actually stores (db.py's tables). Update them when
that changes, and bump UPDATED.
"""
CONTACT = "paperbot.support@gmail.com"
UPDATED = "3 October 2026"

NAV = r"""<nav><div class="wrap nav-in">
  <a class="brand" href="./"><img src="img/paper-180.png" alt="" width="26" height="26">Paper</a>
  <a class="link" href="./#setup">Setup</a>
  <a class="link" href="./#features">Features</a>
  <a class="link" href="commands.html">Commands</a>
  <a class="dash" href="__DASHBOARD__">Dashboard</a>
</div></nav>
<style>
.doc{max-width:72ch;padding-block:8px 48px}
.doc h2{font-size:clamp(19px,2.4vw,23px);margin:34px 0 10px}
.doc p,.doc li{color:var(--dim);line-height:1.7}
.doc ul{padding-left:20px}
.doc li{margin-bottom:6px}
.doc strong{color:var(--text);font-weight:600}
.doc a{color:var(--accent-soft)}
</style>
"""

FOOTER = r"""<footer>
  <p><a href="./">Home</a> · <a href="commands.html">Commands</a> ·
  <a href="privacy.html">Privacy</a> · <a href="terms.html">Terms</a> ·
  <a href="mailto:__CONTACT__">__CONTACT__</a></p>
</footer>"""

PRIVACY = NAV + r"""<div class="wrap">
<header class="page-head">
  <p class="eyebrow">Privacy</p>
  <h1>Privacy Policy</h1>
  <p class="lede">Last updated __UPDATED__.</p>
</header>
<section class="doc">
<p>Paper is a Discord bot run by an individual developer in Queensland,
Australia. This page explains what Paper stores, why, and what you can do
about it. It follows the Australian Privacy Principles, and gives everyone
the rights the GDPR describes, wherever they live.</p>

<h2>What Paper stores</h2>
<ul>
<li><strong>Your Discord user ID</strong>, alongside everything below. Paper
never has your email, phone number or password.</li>
<li><strong>Gacha:</strong> your claimed characters, wishes, likes, notes,
nicknames, karuda, badges, tower, keys and settings.</li>
<li><strong>Levels and activity:</strong> XP, level, message counts and time
in voice for each server, plus daily and weekly totals for leaderboards and
staff reports. Messages are counted, but what they say isn't saved.</li>
<li><strong>Moderation:</strong> warnings, jails, mutes, bans and other cases
(with the reason the moderator gave), jailed members' saved roles, forced
nicknames and staff points.</li>
<li><strong>Things you ask it to keep:</strong> reminders and their text, AFK
status and reason, and server settings such as welcome messages, auto
replies, reaction roles and automod words.</li>
<li><strong>Dashboard login:</strong> your Discord name, avatar and the list
of servers you're in, for 7 days per login. Only a hashed copy of the login
token is stored.</li>
<li><strong>Premium:</strong> payments go through Stripe. Paper stores only
Stripe's customer and subscription IDs and the plan's status, and never sees
card details.</li>
</ul>

<h2>What Paper keeps only briefly</h2>
<ul>
<li><strong>Recent messages</strong> are held in memory, never in the
database, so snipes and chat logs can show deleted or edited text. Snipes
expire after 2 hours, and memory is cleared whenever the bot restarts.</li>
<li><strong>Chat logs</strong> are posted to a channel the server's staff
choose. Those posts live in that server on Discord, not in Paper's
database.</li>
</ul>

<h2>Why</h2>
<p>To run the features you and your server use. Paper doesn't sell or rent
data, doesn't show ads and doesn't build profiles of anyone.</p>

<h2>Who else handles it</h2>
<ul>
<li><strong>Discord</strong>, the platform Paper runs on.</li>
<li><strong>Railway</strong>, which hosts the bot and its database in the
United States.</li>
<li><strong>Cloudflare</strong>, which hosts this website.</li>
<li><strong>Stripe</strong>, which processes payments.</li>
</ul>
<p>A daily backup of the database is sent privately to the bot's owner on
Discord, so it can be restored if something breaks.</p>

<h2>How long it's kept</h2>
<p>Data is kept while it's in use. A server's data stays after Paper leaves,
in case it's added back. You can ask for deletion at any time. Moderation
records stay with the server's staff unless that server asks for them to be
removed.</p>

<h2>Your choices</h2>
<ul>
<li><code>$selfreset</code> and the other self-reset commands clear your own
gacha data.</li>
<li>Server admins can wipe their server's data with the full-reset
commands.</li>
<li>Email <a href="mailto:__CONTACT__">__CONTACT__</a> to see what Paper holds
about you, correct it, or have it deleted. Requests are answered within 30
days.</li>
<li>If you're unhappy with how a request was handled, you can complain to the
Office of the Australian Information Commissioner at
<a href="https://www.oaic.gov.au">oaic.gov.au</a>.</li>
</ul>

<h2>Children</h2>
<p>Paper is for people old enough to use Discord under Discord's own rules
(13 or older in most countries).</p>

<h2>Changes</h2>
<p>Changes are posted here, and the date at the top changes with them.</p>
</section>
""" + FOOTER + "\n</div>\n"

TERMS = NAV + r"""<div class="wrap">
<header class="page-head">
  <p class="eyebrow">Terms</p>
  <h1>Terms of Service</h1>
  <p class="lede">Last updated __UPDATED__.</p>
</header>
<section class="doc">
<p>By using Paper or adding it to a server, you agree to these terms and to
Discord's <a href="https://discord.com/terms">Terms of Service</a> and
<a href="https://discord.com/guidelines">Community Guidelines</a>.</p>

<h2>Using Paper</h2>
<ul>
<li>Don't use Paper to break Discord's rules or the law, to harass people, or
to spam.</li>
<li>Don't try to break, overload or exploit Paper, or get Premium without
paying for it.</li>
<li>Server staff are responsible for how they use the moderation tools, chat
logs and anything Paper posts for them.</li>
</ul>

<h2>Gacha items</h2>
<p>Characters, karuda, rolls, badges and other in-bot items have no
real-world value. They can't be sold or traded for money, and they may be
rebalanced or reset.</p>

<h2>Premium</h2>
<ul>
<li>Premium is sold per server (Premium, Plus or Lifetime) or per player
(Player Premium) through Stripe, at the prices shown when you buy.</li>
<li>Subscriptions renew monthly until cancelled. Cancelling stops the next
renewal, and Premium lasts until the end of the period already paid
for.</li>
<li>"Lifetime" means for as long as Paper keeps running.</li>
<li>Nothing here limits your rights under the Australian Consumer Law,
including refunds when something is faulty or not as described.</li>
</ul>

<h2>Availability</h2>
<p>Paper is provided as it is. It aims to stay up and accurate, but it can go
down, change or lose data. As far as the law allows, the developer isn't
liable for indirect losses from using it.</p>

<h2>Ending things</h2>
<p>You can remove Paper from a server or stop using it at any time. Access can
be removed from anyone who breaks these terms.</p>

<h2>Law</h2>
<p>These terms are governed by the laws of Queensland, Australia.</p>

<h2>Contact</h2>
<p><a href="mailto:__CONTACT__">__CONTACT__</a></p>
</section>
""" + FOOTER + "\n</div>\n"


def fill(body: str) -> str:
    return body.replace("__CONTACT__", CONTACT).replace("__UPDATED__", UPDATED)
