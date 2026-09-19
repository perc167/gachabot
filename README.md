# Gacha bot

A Mudae-style Discord gacha bot: roll random characters, claim them with a
button, collect kakera, keep a wishlist, trade with other players. Rates and
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
| `$mm [@user] [likes\|name\|recent\|kakera]` | Browse a harem |
| `$im <name>` | Character card |
| `$search <text>` | Search by character or series |
| `$divorce <name>` | Release a character, refunds half its kakera |
| `$note <name> \| <text>` | Annotate one of your characters |
| `$top` | Biggest harems in the server |
| `$k [@user]` | Kakera balance and harem worth |
| `$daily` | Free kakera every 20h |
| `$pay @user <amount>` | Send kakera |
| `$richest` | Kakera leaderboard |
| `$wish <name>` | Get pinged and a head start when it rolls |
| `$unwish <name>` / `$wishlist [@user]` / `$wishedby <name>` | Wishlist management |
| `$gift @user <name>` | Give a character away (they confirm) |
| `$trade @user <yours> \| <theirs>` | Swap two characters (both confirm) |
| `$settings` / `$set <key> <value>` / `$resetsettings` | Per-server tuning (Manage Server) |
| `$pool` | Pool size and most-liked characters |
| `$missingart [series]` | Characters that still need artwork |
| `$setimage <id> <url>` | Give a character its art (owner-only) |
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

**Kakera.** Rolling a character someone already owns drops a Kakera button
instead. Grabbing pays out the character's `base_kakera` scaled by the server's
`kakera_rate`, with a ±20% jitter — 60% payout if the character is not yours.
Gated by `kakera_interval_minutes`.

**Ranks and value.** Every character carries two popularity ranks, 1 being the
most popular, exactly as Mudae does:

- **Claim rank** — how sought-after they are to actually own
- **Like rank** — how many people want them

Both appear on the card. `base_kakera` is derived from the average of the two
on a front-loaded curve, so it runs from **20** for a rank-10000 nobody to
**1300** for rank 1, and the drop-off near the top is steep. Rarity tier is
then read off that value, so tier, rank and worth are three views of one
number rather than three unrelated systems.

Rarity does **not** change your odds of rolling someone. Rolls are a flat,
uniform pick across the pool, which is what Mudae does — rarity expresses
itself through kakera payouts and through who reaches the Claim button first.
If you ever want weighted rolls, the change is a weight per tier applied in
`Database.random_character`.

**Albums.** A character can hold any number of images. A roll shows one at
random, so the same character looks different each time they appear. `$album
<name>` flips through them, `$addimage <id> <url...>` adds, `$delimage <id> <n>`
removes. The first image added becomes the primary one used on harem pages.

**Wishes.** When a wished character rolls, every wisher gets pinged, and for
`wish_protect_seconds` only wishers may press Claim. Wishes are consumed once
the character is claimed.

## The character pool

`$import` loads `data/characters.json` — currently **149 characters across 20
series** (Naruto, One Piece, Dragon Ball, Attack on Titan, Demon Slayer, Jujutsu
Kaisen, and so on).

### How kakera values were decided

Values are not hand-typed. `tools/build_roster.py` computes each one from two
things:

```
base_kakera = how famous the series is + how central the character is
```

Series sit in fame tiers (`S` = household name, down to `C` = niche), and each
character is a `lead`, `main` or `support` within their own series. So Naruto
Uzumaki lands at 115 and Ein from Cowboy Bebop at 56. Disagree with a ranking?
Edit the tables at the top of that file and re-run:

```bash
python tools/build_roster.py
```

Then `$import` again — matching is on `name` + `series`, so it updates in place
rather than duplicating, and nobody loses a character they already claimed.

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

Everything after the series is optional (art blank, likes 0, kakera 50). Or edit
`data/characters.json` directly — it's a list of objects with `name`, `series`,
and optional `image_url`, `likes`, `base_kakera` — and run `$import`. You can
also attach your own `.json` file to the `$import` message.

## Layout

```
start-bot.bat       double-click launcher, finds Python and starts the bot
bot.py              entry point, cog loading, error handling
tools/build_roster.py  regenerates data/characters.json and its kakera values
tools/fetch_art.py     fills in image_url from the AniList API
config.py           settings table, rarity tiers, env vars
db.py               all SQL; every query lives here
utils.py            cooldown bookkeeping, kakera math, embed building
views.py            Paginator and Confirm buttons
cogs/rolling.py     $w, the Claim and Kakera buttons
cogs/harem.py       browsing, lookup, divorce, leaderboard
cogs/kakera.py      balance, daily, pay, richest
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

It loads all eight cogs, then drives claims, races, cooldowns, kakera, wishes,
trades, divorces, settings and embed building against a throwaway database —
about 70 assertions, a few seconds, no Discord connection.

Adding a setting is one line in `GUILD_SETTINGS` — `$settings` and `$set` pick
it up automatically.

## Notes

- Storage is SQLite (`gacha.db`), created on first run. Back it up by copying
  the file.
- Concurrent claims are safe: the marriage table's primary key means the first
  writer wins and everyone else gets "Someone beat you to it."
- Buttons expire but the message stays; expired views disable their buttons.
