# Gacha bot

A Mudae-style Discord gacha bot: roll random characters, claim them with a
button, collect karuda, keep a wishlist, trade with other players. Rates and
cooldowns are configurable per server.

## Setup

Six steps, about ten minutes. You need a Discord server where you can add bots
(make a new empty one if you like — click the **+** at the bottom of your server
list in Discord).

### Step 1 — Create the bot account

A bot is its own Discord account that your code logs into. You make one here:

1. Go to **https://discord.com/developers/applications**, sign in.
2. Top right: **New Application**. Give it a name (this is the name people will
   see) and click **Create**.
3. In the left sidebar, click **Bot**.

Leave this page open — the next two steps happen right here.

### Step 2 — Get the token

The token is the bot's password. Your code needs it to log in.

1. On that **Bot** page, click **Reset Token**, then **Yes, do it**.
2. Click **Copy**. You can only see it once — if you lose it, just reset again.
3. Open the file **`.env`** in this folder (Notepad is fine). Find this line:

   ```
   DISCORD_TOKEN=paste-your-bot-token-here
   ```

   Replace `paste-your-bot-token-here` with what you copied. No quotes, no
   spaces around the `=`. It should end up looking like
   `DISCORD_TOKEN=MTIzNDU2Nzg5...`

4. Save the file.

> Never post this token anywhere. Anyone who has it controls your bot. If it
> leaks, hit **Reset Token** and it becomes worthless.

### Step 3 — Turn on the two switches

Still on the **Bot** page, scroll down to **Privileged Gateway Intents** and
turn ON both of these:

- **MESSAGE CONTENT INTENT** — lets the bot read `$w` and friends
- **SERVER MEMBERS INTENT** — lets it recognise `@mentions` in trades

Click **Save Changes** at the bottom. **The bot will refuse to start without
these**, and it will tell you so if you forget.

### Step 4 — Invite it to your server

1. Left sidebar: **OAuth2**, then find **OAuth2 URL Generator**.
2. Under **SCOPES**, tick **`bot`**.
3. A **BOT PERMISSIONS** box appears below. Tick:
   **Send Messages**, **Embed Links**, **Attach Files**, **Read Message History**.
4. Copy the long URL at the bottom, paste it into your browser, pick your
   server, and click **Authorize**.

The bot appears in your member list, offline. That's expected — it comes online
in step 5.

### Step 5 — Tell it who you are, then start it

`BOT_OWNERS` is who is allowed to add characters. That should be you.

1. In Discord: **Settings** (gear, bottom left) → **Advanced** → turn on
   **Developer Mode**.
2. Right-click your own name anywhere → **Copy User ID**.
3. In **`.env`**, replace `paste-your-user-id-here` with that number. Save.
4. Now start it: **double-click `start-bot.bat`** in this folder.

That's it. The launcher finds Python for you, installs what's needed the first
time, and starts the bot.

When it works you'll see `logged in as YourBotName`. The bot goes green in
Discord. Leave that black window open — closing it turns the bot off.

<details>
<summary>Prefer to type the commands yourself?</summary>

```bash
pip install -r requirements.txt
```

```bash
python bot.py
```

If cmd says `'python' is not recognized`, Python was installed without being
added to your PATH. Either use `start-bot.bat`, which works around it, or fix
it permanently: re-run the Python installer, choose **Modify**, click Next, and
tick **Add Python to environment variables**. Then close and reopen cmd.
</details>

### Step 6 — Load the characters and play

In any channel in your server, type:

```
$import
```

That loads the starter characters. Then:

```
$w
```

You'll get a character with a **Claim** button. Press it. You're playing.

`$help` lists everything else.

## Keeping everyone's progress when you update the bot

**Attach a volume.** Without one, every deploy starts from an empty database:
claims, karuda, tutorials, notes, badges, nicknames — all of it gone, because
a host like Railway rebuilds the container from scratch and keeps nothing
that was written beside the code.

On Railway:

1. Open the service → **Variables** → the **Volumes** tab (or *New* → *Volume*).
2. Mount it at **`/data`**. Any path works; the bot finds it either way.
3. Redeploy.

There is nothing to configure. Railway sets `RAILWAY_VOLUME_MOUNT_PATH` when a
volume is attached, and the bot puts its database there on its own. Hosting
somewhere else? Set `DB_PATH` to a file on persistent storage.

To check, run `$dbinfo`:

- 🔒 **on a volume** — your data survives redeploys.
- ⚠️ **on disposable storage** — it does not, and it says so in red.

The startup log says the same thing, loudly, every time the bot boots without
a volume.

### What a volume does and does not cover

| | Survives a deploy |
|---|---|
| Claims, karuda, tutorials, notes, badges, nicknames | only with a volume |
| The character roster | always — it ships in the repo |

The roster is loaded automatically the first time the bot starts with an empty
pool, so a fresh volume needs no `$import`. You only need `$import` after
changing `data/characters.json` yourself.

### Getting a copy out

`$export` dumps the roster to a file. Claims and balances have no export —
they only exist in the database — so a volume is the only thing that keeps
them.

## If something goes wrong

| What you see | What it means |
|---|---|
| `SETUP NEEDED: the bot does not have a token yet` | Step 2 — the token is still the placeholder text in `.env` |
| `Discord rejected that token` | The token is mistyped, cut short, or was reset after you copied it. Reset it and paste again |
| `SETUP NEEDED: two switches are still off` | Step 3 — the two intents |
| `'python' is not recognized` | Python isn't on your PATH. Use `start-bot.bat` instead — it finds Python on its own |
| `.env` is missing | Copy `.env.example` to `.env` and fill it in. It is never copied automatically, because it holds your token |
| Bot is online but ignores `$w` | It can't see messages: the Message Content intent (step 3), or it lacks Send Messages in that channel |
| `BOT_OWNERS is empty` warning | Step 5 — your user ID. Everything works except `$import` and `$addchar` |
| Nothing happens on `$w` | Run `$import` first — an empty pool has nothing to roll |

## Commands

| | |
|---|---|
| `$w` | Roll a character (aliases: `$wa`, `$m`, `$roll`) |
| `$rolls` | Rolls left and every cooldown |
| `$mm [@user] [likes\|name\|recent\|karuda]` | Browse a harem |
| `$im <name>` | Character card |
| `$search <text>` | Search by character or series |
| `$divorce` | Release a character — pick from a menu |
| `$note` | Annotate one of yours — pick, then type in a box |
| `$top` | Biggest harems in the server |
| `$series <name>` | A series and everyone in it |
| `$divorceall` / `$divorceseries` / `$divorceallbut [n]` | Let go in bulk, with confirmation |
| `$like <name>` / `$unlike` / `$likelist` | Vote for characters |
| `$mostliked` / `$likepos <name>` | This server's favourites |
| `$wishseries <name>` / `$wishremoveall` | Wishlist in bulk |
| `$profile [@user]` | Balance, best claim, cooldowns |
| `$stats` | Pool size and what this server has claimed |
| `$myid` / `$invite` / `$ping` / `$uptime` | Utility |
| `$quiz` | Name the character in the picture |
| `$slots [bet]` | Three reels, karuda on the line |
| `$duel @user [bet]` | Your best character against theirs |
| `$alea [low] [high]` / `$jankenpon` | Dice and rock-paper-scissors |
| `$k [@user]` | Karuda balance and shard collection |
| `$dk` | Two shards: keep one, others may snipe the rest |
| `$shards` | What each shard pays, and its odds |
| `$pay @user <amount>` | Send karuda |
| `$richest` | Karuda leaderboard |
| `$shop` | What karuda buys |
| `$buyrolls [n]` | Buy extra rolls for this window |
| `$resetclaim` | Clear your claim cooldown |
| `$wishslot` | Buy a permanent wishlist slot |
| `$wish <name>` | Get pinged and a head start when it rolls |
| `$unwish <name>` / `$wishlist [@user]` / `$wishedby <name>` | Wishlist management |
| `$gift @user` | Give a character away — pick from a menu |
| `$trade @user` | Swap characters — you each pick from a menu |
| `$settings` / `$set <key> <value>` / `$resetsettings` | Per-server tuning (Manage Server) |
| `$setrolls` / `$setclaim` / `$setinterval` / `$setrate` … | Friendly setters for the same settings |
| `$prefix <char>` | Change the prefix for this server |
| `$disable` / `$enable` / `$enableall` / `$disablelist` | Switch commands off per server |
| `$channelallow` / `$channeldeny` / `$channellist` | Limit the bot to certain channels |
| `$access` / `$redeem <key>` | Access status and key redemption |
| `$addcustom Name \| Series \| url` | A character only this server rolls |
| `$customlist` / `$imgcustom` / `$namecustom` / `$valuecustom` / `$deletecustom` | Manage them |
| `$badges` / `$buybadge <name>` | One-off perks bought with karuda |
| `$kt` / `$ktup` / `$toptower` | The karuda tower, climbed a floor at a time |
| `$perks` | What your badges and tower add up to |
| `$setsoulmate` / `$soulmate` / `$soulmates` | Name one character your soulmate |
| `$key` / `$keys` / `$keyed` | Spend keys to raise a character's value |
| `$pool` | Pool size and most-liked characters |
| `$missingart [series]` | Characters that still need artwork |
| `$setimage <id> <url>` | Give a character its art (owner-only) |
| `$addseries <name>` | Pull one series in from AniList |
| `$addchar` / `$editchar` / `$delchar` / `$import` / `$export` | Owner-only pool management |

## How the game works

**Rolling.** Each player gets `roll_limit` rolls per `roll_reset_minutes`
window. The counter refills in blocks — when the window expires, you are back
to full.

**Claiming.** A roll of an unclaimed character shows a Claim button for
`claim_window_seconds`. Clicking it marries the character to you and starts
your `claim_interval_minutes` cooldown. A character can only be married by one
person *per server* — each server has its own independent game state over a
shared character pool.

**Karuda.** The currency. Rolling a character someone already owns drops a
Karuda button instead of a Claim button; grabbing pays `karuda_grab_percent`
of that character's value (12% by default), with a ±20% jitter, and 60% of
that if the character is not yours. Gated by `karuda_interval_minutes`.

**The economy is a loop, not a tap.** An active day earns roughly 900 karuda,
and the shop is where it goes: extra rolls now, an earlier claim, a wider
wishlist. Two things are deliberately closed off — a grab pays a slice of a
character's worth rather than all of it, and divorcing refunds nothing by
default, because claiming costs nothing and a refund turned the claim
cooldown into a money printer. Both are settings
(`karuda_grab_percent`, `divorce_refund_percent`) if you want it looser.

**Shards.** `$dk` shows two shards and you keep one, each rolled from
eight types, and which one you get decides the payout:

| Shard | Payout | Chance |
|---|---|---|
| Karuda Dust | ×1 | 50% |
| Verdite | ×1.6 | 21.5% |
| Aurum | ×2.4 | 13.5% |
| Ember | ×3.6 | 8% |
| Azure | ×5.5 | 4.5% |
| Obsidian | ×9 | 1.5% |
| Prism | ×14 | 0.8% |
| Lumen | ×25 | 0.2% |

**Sniping.** You get first refusal on your own drop for
`dk_protect_seconds` (20 by default). After that — or the moment you take
yours — anyone in the channel can take the shard you left. Snipers receive
`dk_snipe_percent` of it (50% by default), so a busy server does not quietly
double everyone's daily income, and `dk_snipe 0` turns it off entirely.

One balance, so shards are about the moment of the pull rather than six
separate wallets. Every type you have pulled is tracked and shown on `$k`.
`$shards` lists the table above live. The icons start as plain Unicode. To use the
crystal art, run `python tools/make_shards.py` and upload the files from
`assets/shards/` as server emoji, named exactly as the shard keys — `dust`,
`verdite`, `aurum`, `ember`, `azure`, `obsidian`, `prism`, `lumen`. The bot
looks emoji up by name at runtime, so there are no ids to copy and nothing to
configure; `$shards` tells you how many it can currently see.

**Ranks and value.** Every character carries two popularity ranks, 1 being the
most popular, exactly as Mudae does: a **claim rank** for how sought-after they
are, and a **like rank** for how many people want them. Both appear on the
card. Value is derived from the average of the two on a front-loaded curve,
running from 20 karuda for a rank-10000 nobody to 1300 for rank 1.

**There are no rarity tiers.** A character's worth is its karuda value and its
ranks — one number, read three ways, rather than a separate tier system laid
on top. Rolls are a flat, uniform pick across the pool, as in Mudae.

**Albums.** A character can hold any number of images. A roll shows one at
random, so the same character looks different each time they appear. `$album
<name>` flips through them, `$addimage <id> <url...>` adds, `$delimage <id> <n>`
removes. The first image added becomes the primary one used on harem pages.

**Wishes.** When a wished character rolls, every wisher gets pinged, and for
`wish_protect_seconds` only wishers may press Claim. Wishes are consumed once
the character is claimed.

## The character pool

`$import` loads `data/characters.json` — **102,040 characters across
13,263 series**, every one with artwork, built by `tools/fetch_roster.py`
from AniList.

### How the sweep reaches six figures

AniList will not paginate past **5,000 entries of any sorted list**. Ask it
for "the most popular anime" and you get 5,000 shows and a closed door, which
is nowhere near enough casts for a roster this size. The same cap is why the
global character list cannot simply be read off in favourites order.

The way through is that the cap is per *query*, not per database. A query
narrowed to one release year is its own 5,000-entry budget, so the fetcher
walks the calendar instead of one long list:

```bash
python tools/fetch_roster.py --count 100000 --manga-years
```

Newest year backwards, anime first and then manga, cutting a year into months
whenever one year is itself too big to read. The windows tile the whole
calendar with no gaps, so every title AniList knows about is reachable.

Three details that matter more than they look:

- **The reported total is a lie.** AniList clamps `pageInfo.total` at the same
  5,000, so a year holding twenty thousand titles reports exactly five
  thousand — indistinguishable from one that really has five thousand. The
  split therefore fires on *reaching* the cap, never on exceeding it, because
  nothing ever exceeds it.
- **Fuzzy dates.** AniList files plenty of older titles with a year and no
  month at all, which reads as `YYYY0000`. A month split starts its first
  window there rather than at `YYYY0100` — starting at January would step
  straight over every one of them.
- **Which series someone is filed under.** A character in six shows is kept
  under the most popular one, tracked as the sweep runs rather than taken from
  whichever window happened to come first.

It is paced to AniList's live limit of 30 requests a minute, so a full sweep
takes about two hours. That is long enough to be worth protecting: it
checkpoints as it goes, Ctrl-C still writes out what it has, and a phase that
fails is reported rather than throwing the rest away. `--resume <file>` picks
up from an earlier run instead of repeating it.

### How karuda values are decided

Nothing is hand-typed. Every character carries their real AniList favourites
count, the whole set is sorted by it, and value is mapped from **rank on a log
scale**:

```
rank 1 → 1300 karuda        rank 300 → 300        rank 102,040 → 20
```

The curve is pinned so it crosses 300 karuda at rank 300 exactly. That pin is
computed from the pool size rather than fixed, which is why growing the roster
from 30,000 to 102,040 left **295 characters** above 300 karuda
instead of tripling them. Being worth something means being genuinely
well-known, whatever the roster's size. Satoru Gojou tops it.

Re-running the fetcher and `$import`-ing again updates in place — matching is
on `name` + `series`, so nobody loses a character they already claimed.

### Rolling out of a pool this big

A flat roll punishes size: over 102,040 characters, a uniform draw shows
someone from the top thousand about **once in a hundred rolls**. That is a
lottery, not a game.

So `roll_bias` (0–100) pulls the draw towards the well-known end of the
ranking. It is a percent rather than a curve so that it means something:

| `roll_bias` | chance a roll is top-1,000 |
|---|---|
| 0 (flat) | 1.0% |
| 35 (default) | 3.4% |
| 100 | 11.1% |

The default of **35** is chosen so a 102,040-character pool rolls exactly
the way a flat 30,000-character one did — the roster tripled, the feel did
not. Nobody is ever excluded: the whole tail still rolls, just not with equal
weight, and characters your own server invented keep precisely their share.

```
$set roll_bias 0     # a pure lottery across every character
$set roll_bias 100   # mostly faces people recognise
```

### Adding a niche series

Sweeping the calendar rather than a popularity list means niche titles now
arrive on their own — MILGRAM sits at popularity 6,870 and used to be missed
entirely; all twelve of its cast are in the roster without being asked for.

Anything still missing can be pulled in one series at a time:

```
$addseries MILGRAM
```

```bash
python tools/add_series.py "MILGRAM" --dry-run
```

Every character stores their favourites count, so a newcomer is placed by
counting how many existing characters have more — exact, and without
renumbering 102,040 rows.

### Artwork

**Every character ships with no image.** That is deliberate: anime character art
is copyrighted, and a bot that hotlinks scraped wiki images is asking for
trouble, especially a public one. Names, series and stats are just facts and are
fine to ship.

Fill art in yourself, using images you have the right to use:

```
$missingart              # what still needs art, most valuable first
$missingart naruto       # narrow it to one series
$setimage 42 https://... # attach art to character 42
```

Or pull it from AniList's public GraphQL API, which is documented and meant to
be called by apps:

```bash
python tools/fetch_art.py --dry-run
```

```bash
python tools/fetch_art.py
```

`--dry-run` reports what it would change without writing. Other flags:
`--series Naruto` to do one show, `--force` to replace art already set,
`--limit N` to try a handful first, `--delay` to change the request spacing
(default 1.5s, well inside AniList's rate limit).

It will not guess. A match needs the **series** to line up *and* the **name** to
be close, or the character is reported and left alone — wrong art is worse than
none. The matcher handles AniList's romanisation (`Tanjirou` for Tanjiro) and
its name ordering (`Gokuu Son` for Son Goku). Matched characters gain a
`source` and `anilist_id` field, and the previous file is kept as
`data/characters.json.bak`.

Run `$import` afterwards to push the art to the bot.

Characters without art still roll, claim and trade perfectly well — the card
just shows a note where the picture goes.

### Adding characters by hand

```
$addchar Sakura Haruno | Naruto
$addchar Sakura Haruno | Naruto | https://example.com/art.png | 0 | 98
```

Everything after the series is optional (art blank, likes 0, karuda 50). Or edit
`data/characters.json` directly — it's a list of objects with `name`, `series`,
and optional `image_url`, `likes`, `base_karuda`, `images` — and run `$import`. You can
also attach your own `.json` file to the `$import` message.

## Layout

```
start-bot.bat       double-click launcher, finds Python and starts the bot
bot.py              entry point, cog loading, error handling
tools/build_roster.py  regenerates data/characters.json and its karuda values
tools/fetch_art.py     fills in image_url from the AniList API
config.py           settings table, shard types, card colours, env vars
db.py               all SQL; every query lives here
utils.py            cooldown bookkeeping, karuda math, embed building
views.py            Paginator and Confirm buttons
cogs/rolling.py     $w, the Claim and Karuda buttons
cogs/harem.py       browsing, lookup, divorce, leaderboard
cogs/karuda.py      balance, daily shard pulls, pay, richest
cogs/wishlist.py    wishes
cogs/trading.py     gift and trade
cogs/admin.py       pool management, import/export
cogs/settings.py    per-guild config
cogs/help.py        the help embed
smoke_test.py       loads every cog, exercises the game logic, no token needed
```

Before you touch anything, check it still runs:

```bash
python smoke_test.py
```

It loads all eight cogs, then drives claims, races, cooldowns, karuda, wishes,
trades, divorces, settings and embed building against a throwaway database —
about 70 assertions, a few seconds, no Discord connection.

Adding a setting is one line in `GUILD_SETTINGS` — `$settings` and `$set` pick
it up automatically.

## Badges and the tower

Two long-term karuda sinks, both feeding one perks table.

**Badges** are one-off purchases: Collector (+2 rolls), Prospector (+4% grab),
Devoted (+2 wishes), Swift (−15% claim wait), Lucky (+15% daily), Archivist
(+1 roll, +2% grab). `$badges` lists them, `$buybadge <name>` buys one.

**The tower** is ten floors climbed one at a time, each costing more than the
last — 2,500 for the first, 160,000 for the tenth, 429,000 for the lot.
`$kt` shows where you are, `$ktup` climbs.

`$perks` shows what it all adds up to. Everything stacks into one effect and
is applied where it matters — the roll budget, the claim cooldown, the grab
percentage, wishlist size and daily payouts — rather than being a number on a
profile. A fully kitted player rolls about half again as often as a new one,
not ten times, and the claim reduction is capped at 60% so the cooldown never
disappears.

## Minigames

Three, each doing a different job in the economy.

**`$quiz`** shows a character's portrait and the series; first person to type
the name wins karuda, scaled so obscurer characters pay more. Answers accept
any distinctive part of the name, so `gojou` counts for Satoru Gojou —
requiring the exact romanisation would make it a spelling test.

**`$slots [bet]`** spins three reels. Three of a kind pays 10×, three Obsidian
25×, a pair returns 1.4×. Payback is about 93%, so the table is a sink.

**`$duel @user [bet]`** puts your most valuable character against theirs, both
sides confirming. Value tilts the odds without deciding them, so an underdog
can win. Karuda only moves between players; the duel creates none.

## Soulmates and keys

**A soulmate** is one character you single out with `$setsoulmate`, picked
from your harem. They carry a 💖 on their card, appear on `$soulmates`, and
grant a small perk (+5% grab, +5% daily) — a statement rather than a build.
Free and reversible. If you trade them away the card says so, rather than
quietly pretending the bond still holds.

**Keys** raise a character's worth. One comes with every tower floor you
climb; `$key` spends one on a character you own, adding +15% to their value
per level up to five levels. `$keys` shows what you hold, `$keyed` what you
have spent them on. Key levels are per server and follow the character, so a
keyed character is worth more to whoever owns them.

## Custom characters

A server can invent its own with `$addcustom Name | Series | image url`
(Manage Server). They live in the same table as the shared pool but carry the
guild's id, so they roll, claim, trade and appear in albums exactly like
anything else — and **only in the server that created them**. Every lookup is
scoped, and a test rolls three hundred times in a second server to confirm one
never leaks.

`custom_limit` caps how many a server may add; the default is 50.

## Command names

Most Mudae names work: `$w`, `$h`, `$m`, `$mm`, `$im`, `$k`, `$dk`, `$wl`,
`$dv`, `$tr`, `$lk`, `$ll`, `$s`, `$pr`, `$ru`, `$sl`, `$br` and so on. There
are 79 commands under about 243 names. `$help` sends the list to your DMs, one section at a time.

## Early players and keys

Everything is free. The bot still records **when each player and server first
appeared**, and supports redeemable keys, because neither can be reconstructed
after the fact — if paid features ever arrive, the people who were here first
have to be identifiable, and that only works if it was written down from the
beginning.

- `$access` shows when someone started and whether they hold a key
- `$redeem <key>` claims one, `$genkey` (owner) mints them and DMs them over
- `FOUNDER_CUTOFF` in `config.py` is `0`, meaning *everyone so far counts*.
  Set it to a timestamp at the moment you start gating something, not before.

Nothing checks any of this yet. It is only bookkeeping, so the option stays
open.

## Notes

- Storage is SQLite (`gacha.db`), created on first run. Back it up by copying
  the file.
- Concurrent claims are safe: the marriage table's primary key means the first
  writer wins and everyone else gets "Someone beat you to it."
- Buttons expire but the message stays; expired views disable their buttons.
