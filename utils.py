"""Shared helpers: cooldown bookkeeping, karuda math, embed building."""
import json
import os
import time

import discord

import config
import perks


def now() -> int:
    return int(time.time())


def fmt_duration(seconds: int) -> str:
    """'2h 15m' / '45s' — used for every cooldown message."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if secs and minutes < 5:
        return f"{minutes}m {secs}s"
    return f"{minutes}m"


# The bot's own emoji, uploaded to the application rather than to any server:
# {name: "<:name:id>"}. Discord lets an application hold two thousand of these
# and use them in every server it is in, which is how a bot ships its own
# icons instead of asking each server to paste them in.
_app_emojis = {}


def set_app_emojis(mapping: dict):
    global _app_emojis
    _app_emojis = dict(mapping or {})


def _emoji(name: str, fallback: str) -> str:
    """The bot's own emoji by that name, then a server's, then the plain one."""
    found = _app_emojis.get(name)
    if found:
        return found
    if _bot is not None:
        guild_emoji = discord.utils.get(_bot.emojis, name=name)
        if guild_emoji:
            return str(guild_emoji)
    return fallback


# Set once at startup so icon lookups can see the server's custom emoji.
# A module-level binding rather than a parameter threaded through every embed
# helper: which icon to draw is presentation, not something callers decide.
_bot = None


def use_emoji_from(bot):
    """Remember the bot, so shard icons can resolve uploaded emoji."""
    global _bot
    _bot = bot


def shard_icon(key: str) -> str:
    """The uploaded crystal for this shard, or the Unicode fallback.

    The bot uploads assets/shards/ to itself the first time it starts and
    finds them missing, so this is normally the bot's own emoji. A server
    that already had one by the same name still works.
    """
    return _emoji(key, config.shard(key)[2])


def badge_icon(key: str, fallback: str, level: int = 1) -> str:
    """The badge's emoji at this level, or the plain one before the upload.

    Each badge has an icon per level - a bare shape at I, a halo at IV - so
    the list shows what somebody has climbed to, not just which badge it is.
    Level 0 borrows the level I icon, since there is nothing else to show.
    """
    wanted = max(1, int(level or 1))
    return (_emoji(f"badge{key}{wanted}", "")
            or _emoji(f"badge{key}", "")
            or _emoji(key, fallback))


# Characters whose art no CDN will serve keep their picture in the repo
# instead, recorded as "local:<filename>". Fandom blocks hotlinking, so those
# images are attached to the message rather than linked from it.
LOCAL_ART = "local:"
ART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "assets", "characters")


def local_art_path(image_url):
    """Where a bundled image lives, or None if this is an ordinary URL."""
    if not image_url or not str(image_url).startswith(LOCAL_ART):
        return None
    # basename only: the roster is data, and data does not get to pick which
    # part of the filesystem the bot reads.
    name = os.path.basename(str(image_url)[len(LOCAL_ART):])
    path = os.path.join(ART_DIR, name)
    return path if name and os.path.exists(path) else None


def art_file(image_url):
    """A fresh discord.File for a bundled image, or None.

    Fresh every time on purpose: a File carries an open buffer that one send
    spends, so a paginator flipping back to a page it has already shown needs
    a new one rather than the old one again.
    """
    path = local_art_path(image_url)
    if not path:
        return None
    return discord.File(path, filename=os.path.basename(path))


def art_reference(image_url):
    """What the embed should point at: an attachment, or the URL itself."""
    path = local_art_path(image_url)
    if path:
        return "attachment://" + os.path.basename(path)
    return image_url


def value_with_keys(db, guild_id: int, character, rate_percent: int) -> int:
    """A character's worth including any keys spent on them here."""
    level = db.key_level(guild_id, character["id"])
    return max(1, int(karuda_value(character, rate_percent)
                      * perks.key_multiplier(level)))


# The top of the roster is worth more than the curve alone gives it, and the
# extra fades out rather than stopping dead. A flat boost to the top 200 would
# leave rank 200 worth a third more than rank 201 for no reason anybody could
# see; tapering it away by BOOST_FADE keeps the list monotonic and smooth.
BOOST = 0.30
BOOST_TOP = 200
BOOST_FADE = 600
VALUE_CEILING = 1300


def rank_boost(rank: int) -> float:
    """The multiplier on a rank's value: 1.30 at the top, 1.0 past the fade."""
    if rank <= BOOST_TOP:
        return 1.0 + BOOST
    if rank >= BOOST_FADE:
        return 1.0
    span = BOOST_FADE - BOOST_TOP
    return 1.0 + BOOST * (BOOST_FADE - rank) / span


def value_for_rank(rank: int, total: int) -> int:
    """Rank to base value, matching tools/fetch_roster.py.

    Kept here as well so a series added at runtime is priced on the same
    curve as everything that arrived in the bulk fetch.
    """
    import math

    low, high, premium_rank, premium_value = 20, 1300, 300, 300
    if total <= 1:
        return high
    rank = max(1, min(rank, total))
    t = math.log(rank) / math.log(total)
    pin = math.log(premium_rank) / math.log(total)
    share = (premium_value - low) / (high - low)
    exponent = math.log(share) / math.log(1 - pin) if 0 < pin < 1 else 2.0
    base = low + (high - low) * (1 - t) ** exponent
    return max(low, min(VALUE_CEILING, round(base * rank_boost(rank))))


def claim_score(favourites: int, gender: str) -> float:
    """How much somebody is wanted, as opposed to how well known they are."""
    weight = (config.FEMALE_CLAIM_WEIGHT
              if (gender or "") == "Female" else 1.0)
    return (favourites or 0) * weight


PIN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "pinned_ranks.json")
_pins_cache = None


def pinned_ranks() -> list:
    """The hand-placed top of the list, read once and remembered."""
    global _pins_cache
    if _pins_cache is None:
        try:
            with open(PIN_FILE, encoding="utf-8") as handle:
                _pins_cache = json.load(handle).get("pins", [])
        except (OSError, ValueError):
            _pins_cache = []
    return _pins_cache


def _apply_pins(ordered: list) -> list:
    """Move the pinned characters to their ranks, closing up behind them.

    Everyone else keeps their relative order and slides into whatever is
    left, so pinning somebody to rank 1 costs the rest one place each rather
    than reshuffling the list.
    """
    pins = pinned_ranks()
    if not pins:
        return ordered

    def norm(text):
        return "".join(c for c in (text or "").lower() if c.isalnum())

    by_name = {}
    for row in ordered:
        by_name.setdefault(norm(row["name"]), []).append(row)

    placed, taken = {}, set()
    for pin in pins:
        rank = int(pin.get("rank", 0))
        if rank < 1 or rank in placed:
            continue
        candidates = by_name.get(norm(pin.get("name")), [])
        hint = norm(pin.get("series"))
        if hint:
            candidates = [c for c in candidates
                          if hint in norm(c.get("series"))] or candidates
        # Unqualified names go to the best known of that name, which is what
        # somebody writing "Rem" in a list means.
        candidates = [c for c in candidates if id(c) not in taken]
        if not candidates:
            continue
        chosen = max(candidates, key=lambda c: c.get("favourites") or 0)
        placed[rank] = chosen
        taken.add(id(chosen))

    if not placed:
        return ordered

    rest = [row for row in ordered if id(row) not in taken]
    out, feed = [], iter(rest)
    for position in range(1, len(ordered) + 1):
        if position in placed:
            out.append(placed.pop(position))
        else:
            out.append(next(feed))
    # A pin beyond the end of the roster has nowhere to go; it stays in the
    # natural order rather than being dropped.
    out.extend(placed.values())
    return out


def rerank_roster(rows) -> list:
    """Set like_rank, claim_rank and base_karuda across a whole roster.

    The single place any of this is decided. It used to live in three -
    fetch_roster, add_series and utils - which is exactly the arrangement
    where a curve gets changed in one of them and quietly disagrees with the
    other two.

    like_rank is raw favourites. claim_rank weights them by how much people
    want to own somebody. Value comes from claim_rank, because what a
    character is worth in a gacha is what people will fight over, not what
    they will upvote.
    """
    rows.sort(key=lambda r: (-(r.get("favourites") or 0), r["name"]))
    for position, row in enumerate(rows, 1):
        row["like_rank"] = position

    total = max(1, len(rows))
    by_want = sorted(
        rows,
        key=lambda r: (-claim_score(r.get("favourites"), r.get("gender")),
                       r["name"]),
    )
    by_want = _apply_pins(by_want)
    for position, row in enumerate(by_want, 1):
        row["claim_rank"] = position
        row["base_karuda"] = value_for_rank(position, total)
    return rows


def karuda_value(character, rate_percent: int) -> int:
    """base_karuda already encodes how famous the character is, so the only
    adjustment is the server's own rate."""
    return max(1, int(character["base_karuda"] * rate_percent / 100))


class Cooldowns:
    """Reads and writes the four timers every player has.

    Rolls and claims both refill in blocks read off the clock, so they come
    back for the whole server at the same moment and the claim block always
    ends on a roll block's boundary. Karuda is still a plain ready-at
    timestamp that starts when you use it.
    """

    def __init__(self, db):
        self.db = db

    def roll_window(self, guild_id: int) -> tuple:
        """The window everyone on this server shares: (ends_at, length).

        Read off the clock rather than off each player, so rolls come back
        for everybody at the same moment. With the default hour that is the
        top of every hour. The alternative - a window that starts when you
        personally first rolled - means two people sitting in the same
        channel are told different numbers of minutes, which is what this
        used to do.
        """
        window = self.db.get_setting(guild_id, "roll_reset_minutes") * 60
        window = max(60, window)
        current = now()
        return (current // window) * window + window, window

    def rolls_left(self, guild_id: int, user_id: int) -> tuple:
        """Returns (rolls_left, seconds_until_reset)."""
        player = self.db.get_player(guild_id, user_id)
        earned = perks.effective(self.db, guild_id, user_id)
        limit = self.db.get_setting(guild_id, "roll_limit") + earned["rolls"]
        ends_at, window = self.roll_window(guild_id)
        current = now()

        # A player carrying any window but the current one has not rolled yet
        # this window, whether that is because the window turned over or
        # because the server changed how long it is.
        #
        # Bought rolls sit on top of the allowance and expire with the window,
        # so buying is a top-up rather than a permanent raise.
        if player["rolls_reset_at"] != ends_at:
            self.db.update_player(
                guild_id,
                user_id,
                rolls_used=0,
                rolls_bought=0,
                rolls_reset_at=ends_at,
            )
            return limit, ends_at - current

        allowance = limit + player["rolls_bought"]
        return (
            max(0, allowance - player["rolls_used"]),
            ends_at - current,
        )

    def grant_rolls(self, guild_id: int, user_id: int, amount: int) -> int:
        """Add bought rolls safely. Returns how many they have now.

        The window is settled first. Adding to rolls_bought and only then
        asking how many are left would wipe the purchase whenever the player
        had not yet rolled this window - they would pay and get nothing.
        """
        self.rolls_left(guild_id, user_id)
        player = self.db.get_player(guild_id, user_id)
        self.db.update_player(
            guild_id, user_id,
            rolls_bought=player["rolls_bought"] + amount,
        )
        return self.rolls_left(guild_id, user_id)[0]

    def spend_roll(self, guild_id: int, user_id: int):
        player = self.db.get_player(guild_id, user_id)
        self.db.update_player(guild_id, user_id, rolls_used=player["rolls_used"] + 1)

    def claim_window(self, guild_id: int) -> tuple:
        """The claim window everyone on this server shares: (ends_at, length).

        Read off the clock like roll_window, and rounded up to a whole
        number of roll windows so a claim reset always lands on a roll
        reset. With the defaults - rolls hourly, claims every three hours -
        claims come back at the top of every third hour, and that moment is
        always one where rolls come back too.
        """
        _, roll_length = self.roll_window(guild_id)
        wanted = self.db.get_setting(guild_id, "claim_interval_minutes") * 60
        # Ceiling division: a 90 minute claim interval on an hourly roll
        # window becomes 120, because 90 would drift off the roll boundary
        # every other window and the two timers would stop agreeing.
        blocks = max(1, -(-max(60, wanted) // roll_length))
        window = blocks * roll_length
        current = now()
        return (current // window) * window + window, window

    def claim_ready(self, guild_id: int, user_id: int) -> tuple:
        """Returns (is_ready, seconds_remaining).

        Clamped to the shared window on the way out, not just on the way in.
        A stored time can outlive the rule that produced it - written by the
        old per-player cooldown, or before the server shortened its claim
        interval - and clamping here means no such value can ever hold
        somebody past a reset everybody else is getting.
        """
        player = self.db.get_player(guild_id, user_id)
        ends_at, _ = self.claim_window(guild_id)
        remaining = min(player["claim_ready_at"], ends_at) - now()
        return remaining <= 0, max(0, remaining)

    def start_claim_cooldown(self, guild_id: int, user_id: int):
        ends_at, window = self.claim_window(guild_id)
        # Badges and tower floors shorten the wait, and shortening is the
        # only thing they can do: the personal time is capped at the shared
        # window, so somebody with no perks always waits exactly until the
        # server's next reset rather than a private three hours of their own.
        reduction = perks.effective(self.db, guild_id, user_id)["claim_percent"]
        personal = now() + int(window * (100 - reduction) / 100)
        self.db.update_player(
            guild_id, user_id, claim_ready_at=min(ends_at, personal)
        )

    def karuda_ready(self, guild_id: int, user_id: int) -> tuple:
        player = self.db.get_player(guild_id, user_id)
        remaining = player["karuda_ready_at"] - now()
        return remaining <= 0, max(0, remaining)

    def start_karuda_cooldown(self, guild_id: int, user_id: int):
        minutes = self.db.get_setting(guild_id, "karuda_interval_minutes")
        sooner = perks.effective(self.db, guild_id, user_id)["grab_cooldown"]
        self.db.update_player(guild_id, user_id,
                              karuda_ready_at=now() + int(minutes * 60 * (100 - sooner) / 100))


def character_embed(
    db,
    guild_id: int,
    character,
    *,
    footer: str = None,
    show_owner: bool = True,
    random_art: bool = False,
    image_url: str = None,
) -> discord.Embed:
    """The card shown for a roll, a `$im` lookup, or a harem page.

    `random_art` picks one image at random from the character's album, which
    is what a roll does: the same character can show up wearing a different
    picture each time.
    """
    rate = db.get_setting(guild_id, "karuda_rate")
    owner_id = db.owner_of(guild_id, character["id"]) if show_owner else None
    wishers = db.wishers_of(guild_id, character["id"])

    # One accent colour for everyone; a claimed character goes green so you
    # can tell at a glance whether the button is worth racing for. The
    # unclaimed colour is the server's to choose.
    colour = (config.CLAIMED_COLOUR if owner_id
              else db.get_pref(guild_id, "cardcolour", config.CARD_COLOUR))
    embed = discord.Embed(title=character["name"], colour=colour)

    # Series on its own line, quoted, so the name is what your eye lands on.
    embed.description = f"> {character['series']}"

    if image_url is None:
        image_url = (
            db.random_image(character["id"]) if random_art else character["image_url"]
        )
    # A bundled image that has gone missing from disk reads as "no art"
    # rather than as a broken card.
    if image_url and (not str(image_url).startswith(LOCAL_ART)
                      or local_art_path(image_url)):
        embed.set_image(url=art_reference(image_url))
    else:
        embed.description += (
            f"\n\n*no image yet — `$setimage {character['id']} <url>`*"
        )

    # Three short inline fields read as columns rather than a wall of bullets.
    icon = shard_icon(config.SHARD_TYPES[0][0])
    level = db.key_level(guild_id, character["id"])
    worth = value_with_keys(db, guild_id, character, rate)
    embed.add_field(
        name="Value",
        value=f"{icon} **{worth:,}**"
              + (f"\n\U0001f511 ×{level}" if level else ""),
        inline=True,
    )
    try:
        odds = character["secret_odds"]
    except (IndexError, KeyError):
        odds = 0
    if odds and odds > 0:
        embed.add_field(
            name="Secret",
            value=f"\u2726 1 in **{odds:,}** rolls",
            inline=True,
        )
    elif character["claim_rank"] or character["like_rank"]:
        embed.add_field(
            name="Rank",
            value=(
                f"claim **#{character['claim_rank']:,}**\n"
                f"like **#{character['like_rank']:,}**"
            ),
            inline=True,
        )

    extras = []
    album = db.image_count(character["id"])
    if album > 1:
        extras.append(f"{album} images")
    liked = db.like_count(guild_id, character["id"])
    if liked:
        extras.append(f"{liked} ♥ here")
    if wishers:
        extras.append(f"wished by {len(wishers)}")
    if extras:
        embed.add_field(name="​", value="\n".join(extras), inline=True)

    if owner_id:
        hearts = db.soulmate_holders(guild_id, character["id"])
        mark = " \U0001f496" if owner_id in hearts else ""
        embed.add_field(
            name="Belongs to", value=f"<@{owner_id}>{mark}", inline=False
        )

    if footer:
        embed.set_footer(text=footer)

    return embed


def paginate(lines, per_page: int = 10) -> list:
    """Chop a list of strings into pages."""
    return [lines[i : i + per_page] for i in range(0, len(lines), per_page)] or [[]]


def iter_roster(path: str):
    """Yield character records from a roster file without holding all of it.

    data/characters.json is written one record per line inside a JSON array,
    so it can be read a line at a time. That shape is worth using: a hundred
    thousand characters parsed in one go is around 140MB of Python objects,
    which is real money on a small container and happens on every deploy.

    Anything not in that shape - a hand-written file, a prettified one - is
    loaded whole instead, so nothing stops working for the sake of the
    optimisation.
    """
    with open(path, "r", encoding="utf-8") as handle:
        first = handle.readline().strip()
        second = handle.readline()
        record = None
        streamable = first == "["
        if streamable:
            try:
                record = json.loads(second.strip().rstrip(","))
            except json.JSONDecodeError:
                streamable = False

        if not streamable:
            handle.seek(0)
            payload = json.load(handle)
            if not isinstance(payload, list):
                raise ValueError("expected a JSON list of character objects")
            yield from payload
            return

        yield record
        for line in handle:
            line = line.strip().rstrip(",")
            if not line or line == "]":
                continue
            yield json.loads(line)


def character_card(db, guild_id: int, character, *, random_art: bool = False,
                   image_url: str = None, **kwargs):
    """The card, plus whatever has to be attached alongside it.

    Returns (embed, send_kwargs). Spread the second into send():

        embed, art = utils.character_card(db, gid, character)
        await ctx.send(embed=embed, **art)

    The image is resolved once, here, so the file attached is always the one
    the embed points at. Choosing it twice would let a random-art roll attach
    a different picture than the one it displays.
    """
    if image_url is None:
        image_url = (db.random_image(character["id"]) if random_art
                     else character["image_url"])
    embed = character_embed(db, guild_id, character, image_url=image_url,
                            **kwargs)
    attachment = art_file(image_url)
    return embed, ({"file": attachment} if attachment else {})


def character_pages(db, guild_id: int, character, *, footer: str = None,
                    show_owner: bool = True):
    """One card per image the character has: (embeds, image sources).

    Hand both to views.Paginator and the card flips through the album the way
    Mudae's does. A character with a single picture still gets a list of one,
    and the paginator drops its arrows for that case on its own.
    """
    urls = db.images_for(character["id"]) or []
    if not urls:
        urls = [character["image_url"]] if character["image_url"] else [""]

    embeds = []
    for index, url in enumerate(urls, 1):
        tail = footer or ""
        if len(urls) > 1:
            page = f"Image {index}/{len(urls)}"
            tail = f"{page} • {tail}" if tail else page
        embeds.append(
            character_embed(db, guild_id, character, image_url=url,
                            footer=tail or None, show_owner=show_owner)
        )
    return embeds, urls
