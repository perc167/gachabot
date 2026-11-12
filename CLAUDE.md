# Paper (gachabot)

Paper (renamed from "Yuri" on 2026-09-26) is a Discord bot that mixes a Mudae-style
character gacha with moderation, voice rooms, levels, a web dashboard and paid
Premium. It is for Discord server owners and their members; public site is
https://getpaperbot.com.

## Run / test / deploy (read first)

```bash
pip install -r requirements.txt     # Python 3.12 (.python-version)
python bot.py                       # needs .env with DISCORD_TOKEN, BOT_OWNERS
start-bot.bat                       # Windows launcher: finds Python, installs deps, starts bot
python smoke_test.py                # no Discord/token needed; loads every cog on a temp DB
python tools/build_site.py          # regenerates site/index.html from live commands + roster
python tools/check_site.py          # sanity-checks the built page (charset, viewport...)
```

- **Bot hosting:** Railway service "gachabot" (project "friendly-wisdom"). Build/start live in the
  service's own settings, not a file: NIXPACKS, `python bot.py`, restart ON_FAILURE x10
  (`railway.json` was removed 2026-11-13; Config as Code stops 2026-12-01). `Procfile`: `worker: python bot.py`. Push to `main` on
  github.com/perc167/gachabot redeploys. The same process serves the web dashboard
  (aiohttp, `cogs/dashboard.py`) at https://gachabot-production-fbd6.up.railway.app.
- **Database persistence:** a Railway volume (any mount path). `config._database_path()`
  uses `DB_PATH` > `RAILWAY_VOLUME_MOUNT_PATH`/`VOLUME_PATH` > `./gacha.db` (disposable,
  warns at startup). `$dbinfo` shows which.
- **Website:** `.github/workflows/site.yml` builds `site/` and deploys it with
  `wrangler.jsonc` (Workers static assets, name `yuri-gacha`) to
  https://gachabot.perc-1fc.workers.dev on pushes that touch cogs/, bot.py, roster data, etc.
  getpaperbot.com is a separate Cloudflare Pages project "getpaperbot" deployed by hand:
  build with `SITE_URL=https://getpaperbot.com`, copy `site/` to scratch, restore
  `site/*.html`, then `npx wrangler@4 pages deploy <copy> --project-name getpaperbot --branch main`.
- **Local site preview:** `.claude/launch.json` (top folder) config `site` serves
  `gachabot/site` on :8765.

### Environment variable names (values live in `.env` locally / Railway variables)
Core: `DISCORD_TOKEN`, `BOT_OWNERS` (comma list of user ids), `PREFIX` (default `$`).
Storage: `DB_PATH`, `RAILWAY_VOLUME_MOUNT_PATH`, `VOLUME_PATH`, `ART_CACHE`, `ART_CACHE_DIR`, `ART_CACHE_MB`.
Web/OAuth: `PORT`, `PUBLIC_URL`, `RAILWAY_PUBLIC_DOMAIN`, `SITE_URL`, `DISCORD_CLIENT_ID`,
`DISCORD_CLIENT_SECRET`, `DISCORD_AUTHORIZE_URL`, `DISCORD_API_BASE`, `YURI_INVITE`.
Billing: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`, `STRIPE_PLUS_PRICE_ID`,
`STRIPE_LIFETIME_PRICE_ID`, `STRIPE_PLAYER_PRICE_ID`, `STRIPE_API_BASE`, `PREMIUM_PRICE_LABEL`.
Votes: `TOPGG_WEBHOOK_SECRET`. CI secret: `CLOUDFLARE_API_TOKEN` (GitHub Actions).

## Stack
Python 3.12, discord.py >= 2.3.2 (prefix `$` commands + auto-generated slash commands),
python-dotenv, Pillow >= 10.1 (rank/profile/board cards), aiohttp (via discord.py) for the
dashboard, SQLite (single shared connection), Stripe REST API (no SDK), AniList API for roster.
Static site: generated HTML on Cloudflare. Dashboard: `dashboard/index.html` single page.

## Layout
- `bot.py` - entry; `GachaBot`, the ordered `COGS` list (`cogs.slash` must stay last),
  typo suggestions, error handling; one broken cog doesn't take the bot down.
- `config.py` - env loading, DB path logic, `OWNERS`, `GUILD_SETTINGS` table
  (name -> default, min, max, description; `$settings`/`$setconfig` read it).
- `db.py` (~4.3k lines) - `SCHEMA` string + `Database` class, every query lives here.
- `premium.py` - single source for perks: `FEATURES` (feature -> tier), `SETTING_RANGES`
  (per-tier ranges, read via `db.setting_range`/`db.has_feature`). `perks.py`, `billing.py`
  (Stripe checkout/portal/webhook; plans Premium, Plus, Lifetime, per-player `billing.PLAYER`).
- `oauth.py` Discord login; `webparts.py` dashboard Gacha/Moderation/Voice pages + validation.
- `backup.py` - trimmed gzip DB backups (roster omitted) sent by DM; restore swaps
  `<db>.restore` in at next start, keeps `<db>.before-restore`.
- Cards: `rankcard.py`, `profilecard.py`, `boardcard.py`; `artcache.py` image cache;
  `anilist.py`; `translator.py`; `tutorial.py` (onboarding steps); `views.py` (buttons/UI);
  `weekly.py`, `wishes.py`, `utils.py`, `converters.py`, `botprofile.py`.
- `cogs/` - ~50 feature cogs: gacha (rolling, harem, haremextra, karuda, wishlist, trading,
  shop, likes, bulk, bonds, progress, champions, aliases, find, leaderboards), moderation
  (moderation, modtools, modsettings, staffpoints, automod, antinuke, antialt, chatlogs,
  notes), server tools (serverconfig, serversetup/builder = Plus-tier server builder,
  customizer, personalise, toggles, access, custom, backups, utility, events), voice, levels,
  dashboard (web server + Stripe/top.gg webhooks), votes (top.gg, weekly draw), help, slash.
- `data/` - roster JSON (`characters.json` one character per line, extra/secret characters,
  art/frames catalogues), `automod.txt`, `guides/`.
- `assets/` - avatar, `brand/` (source-avatar + generated), badges, shards, character art.
- `site/` - generated public site (`index.html`, `commands.html`, `privacy.html`,
  `terms.html` from `tools/policies.py`, `secret/` art). `tools/` - roster/art fetchers,
  `build_site.py`, `check_site.py`, `make_brand.py`, `make_badges.py`, `rebalance.py`, etc.

## Languages (localize.py)
Code writes English only. `localize.py` patches every way Paper speaks (Messageable.send,
interaction replies/edits/modals, webhooks, Message.edit) and swaps each English line for the
reader's language: their `/language` choice > server default > Discord app locale > English.
- `locales/catalog.json`: every line the code can say, f-strings as `{0}` templates, made by
  `python tools/extract_strings.py` (reads source, never imports it).
- `locales/strings/<code>.json`: catalog line -> translation, 29 languages. Missing lines stay
  English. A translation whose `{fields}` differ from the English is ignored (smoke test fails).
- After adding or changing user-facing text: rerun the extractor, then translate what
  `python tools/extract_strings.py --missing <code>` prints into each strings file.
- `i18n.py` is the older keyed system (`/language` picker, `locales/en.json`); keep using it
  only for the picker. Things Paper reads back off its own messages go in `localize.KEEP_PREFIXES`.
- Not translated: text in images (rank/profile cards) and text people wrote.

## Data flow
Messages/interactions -> cog command -> `Database` (sqlite) -> embed/view reply, with
Pillow cards rendered on demand. Roster ships in `data/characters.json` and is loaded into
`characters`/`character_images` at startup or `$import`. Dashboard: browser -> Discord OAuth
(`/login`, `/callback`, `web_sessions`) -> `/api/*` -> same `Database`. Stripe ->
`/stripe/webhook` -> `guild_premium` / `player_premium`. top.gg -> `/topgg/webhook` ->
karuda banked per vote (claimed with `$vote`).

## Database schema (gacha.db; tables -> columns)
- Roster: `characters`(id, name, series, image_url, likes, base_karuda, source, gender,
  secret_odds, like_rank, claim_rank, guild_id, favourites), `character_images`,
  `character_aliases`, `character_keys`, `character_likes`.
- Players/gacha: `players`(guild_id, user_id, karuda, rolls_used, rolls_reset_at,
  claim_ready_at, karuda_ready_at, daily_ready_at, harem_sort, showcase_id, tuto_step,
  tuto_silent, roll_resets, rolls_daily_at, rt_ready_at, rolls_bought, extra_wish_slots,
  first_seen, premium, tower_floor, keys, soulmate_id, soulmate_set_at), `marriages`,
  `wishes`, `starwishes`, `badges`, `player_items`, `player_prefs`, `shard_pulls`,
  `tower_floors`, `tutorial_progress`, `rank_backgrounds`.
- Premium: `guild_premium`(guild_id, status, until, customer, subscription, buyer_id,
  updated_at, trial_used, tier), `player_premium`, `premium_keys`, `premium_settings`.
- Moderation: `mod_cases`, `mod_config`, `jailed`, `hardbans`, `warn_punishments`,
  `staff_points`, `staff_roles`, `forced_nicks`, `automod_settings/words/exempt`,
  `antinuke_settings/people`, `lockdown_ignore`.
- Levels/activity: `levels`, `level_settings/roles/boosts/ignored/texts`, `monthly_xp`,
  `activity`, `weekly_activity`.
- Voice: `temp_vcs`, `vc_sessions`, `vc_time`, `vc_settings`, `vc_hour_roles`.
- Server config: `guilds`, `guild_settings`, `guild_prefixes`, `disabled_commands`,
  `allowed_channels`, `greetings`, `autoroles`, `reaction_roles`, `autoreacts`,
  `autoresponders`, `invoke_messages`, `bot_profiles`, `server_events`, `reminders`, `afk`.
- Web: `web_sessions`(token_hash, user_id, name, avatar, guilds, expires).
- Key/value prefs in guild 0 hold global state (e.g. `slash_crc`, `vote_channel`, `vote_role`).

## Conventions
- Module docstring at the top of every file explaining *why*; comments explain reasoning
  in plain English. Match that density.
- One settings table per area (`GUILD_SETTINGS`, `premium.FEATURES`/`SETTING_RANGES`) -
  adding a knob should be a one-line change there.
- All SQL lives in `db.py`. Tables use `guild_id` + `user_id`; settings tables are
  `(guild_id, key, value)`.
- Every new `$` command needs a `$help` section (or a TOP/EXTRA entry in `cogs/slash.py`)
  or the smoke test fails. Slash limits: 100 top-level, 25 per group.
- Commit messages: plain sentence, user-facing outcome ("Cap the reactions on one message").
- Premium philosophy: generous; never take away what's free today. Prices in AUD with USD
  options (Premium A$4.99, Plus A$15, Lifetime A$50, Player A$5.99).

## Working rules
- Run `python smoke_test.py` (and `tools/check_site.py` for site changes) before committing.
- Commit and push finished, tested work without asking (user preference); pushing `main`
  redeploys Railway + the site. Never force-push without asking.
- Another session may edit this working tree concurrently: never `git stash`, `git reset`
  or `git checkout -- <file>`; stage only your own files/hunks.
- Never stage `data/character_art.json` or `data/character_art_tags.json` (changed outside our work).
- Read only the schema of `gacha.db`; it holds real player data.

## Known issues / TODO / risks
- Hardcoded old URL `https://gachabot.perc-1fc.workers.dev` in `cogs/about.py:133`,
  `cogs/profile.py:47`, `cogs/dashboard.py:73` and `tools/build_site.py:51` should move to
  getpaperbot.com (then redeploy getpaperbot). Optional: app.getpaperbot.com -> Railway
  (update `PUBLIC_URL` + OAuth redirect).
- `.wrangler/` is not in `.gitignore` (currently untracked) - easy to commit by accident.
- Working tree has ~100 uncommitted files (new `assets/characters/frame-*.jpg`, modified
  frame/extra-character JSON) - likely the art pipeline session's work in progress.
- `wrangler.jsonc` still named `yuri-gacha`; `YURI_INVITE` env name is a leftover of the rename.
- `data/characters.json.bak` sits in the repo folder (`*.bak` ignored).
- Verification: Discord needs 75 servers (was 6 on 2026-10-03); top.gg listing + webhook
  env not confirmed; Discord policy wants paid perks also on Discord Premium Apps.
- No secrets found in git history by pattern scan (2026-10-25). `.env` is ignored.
