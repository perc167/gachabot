"""The dashboard's Gacha, Moderation and Voice pages: what each one shows, and
the checks on what it saves. Levels has its own, in cogs/dashboard.py.

Every save checks everything first and writes nothing if any of it is
wrong, with the same limits the $ commands use: config.GUILD_SETTINGS for
the gacha, the actions in cogs/modtools.py for moderation.

Ids go out as strings, because they're bigger than a JavaScript number can
hold exactly, and come back in as strings too.
"""
import time

import discord

import botprofile
import config
import premium
import weekly
from cogs import automod as automod_cog
from cogs import events as events_cog
from cogs import serversetup
from cogs.modtools import FREE_WARN_PUNISHMENTS, describe_duration, parse_duration
from cogs.toggles import GROUPS, TOGGLES

# How the gacha dials are grouped on the page. Any setting not named here
# still shows, under "Other", so a new one can't go missing.
GACHA_SECTIONS = (
    ("Rolls and claims", ("roll_limit", "roll_reset_minutes", "claim_interval_minutes",
                          "claim_window_seconds", "show_claimed", "roll_bias",
                          "max_marriages", "player_boosts")),
    ("Wishes", ("wish_limit", "wish_protect_seconds")),
    ("Karuda and the daily", ("karuda_interval_minutes", "karuda_rate",
                              "karuda_grab_percent", "divorce_refund_percent",
                              "dk_snipe", "dk_protect_seconds", "dk_snipe_percent")),
    ("Shop prices", ("price_rolls", "rolls_per_purchase", "price_claim_reset",
                     "price_wish_slot")),
    ("Custom characters", ("custom_limit",)),
)
PUNISHMENTS = ("timeout", "jail", "kick", "ban")
MAX_ROWS = 50


def _count(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _channels(guild, kind=discord.TextChannel):
    return [{"id": str(c.id), "name": c.name,
             "category": c.category.name if c.category else ""}
            for c in guild.channels if isinstance(c, kind)]


def _roles(guild):
    top = guild.me.top_role
    return [{"id": str(r.id), "name": r.name,
             "usable": not r.managed and r < top}
            for r in sorted(guild.roles, key=lambda r: -r.position)
            if not r.is_default()]


def _id(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text_channel(guild, value):
    channel = guild.get_channel(_id(value)) if _id(value) else None
    return channel if isinstance(channel, discord.TextChannel) else None


def _usable_role(guild, value):
    role = guild.get_role(_id(value)) if _id(value) else None
    if role and not role.is_default() and not role.managed \
            and role < guild.me.top_role:
        return role
    return None


# --------------------------------------------------------------- overview

def overview(bot, guild) -> dict:
    db = bot.db
    gid = guild.id
    mod_ready = bool(db.get_mod_config(gid, "jail_role"))
    create = db.get_vc_setting(gid, "create_channel")
    levels = bot.get_cog("Levels")
    xp = (f"{levels.setting(gid, 'msg_min')}-{levels.setting(gid, 'msg_max')} XP a message"
          if levels else "")
    allowed = len(db.allowed_channels(gid))
    return {
        "gacha": [f"Prefix {db.get_prefix(gid) or config.PREFIX}",
                  f"{db.get_setting(gid, 'roll_limit')} rolls every"
                  f" {db.get_setting(gid, 'roll_reset_minutes')} minutes",
                  f"Answers in {_count(allowed, 'channel')}"
                  if allowed else "Answers in every channel"],
        "mod": [("Set up" if mod_ready else "Not set up yet: run $setupmod"),
                _count(len(db.staff_roles_of(gid)), "staff role"),
                _count(len(db.warn_punishments_of(gid)), "warn punishment")],
        "voice": [("Join To Create is on" if guild.get_channel(create)
                   else "Join To Create is off"),
                  _count(len(db.hour_roles_of(gid)), "hour role")],
        "levels": [xp, _count(len(db.level_roles_of(gid)), "level role")],
        "extras": [_count(len(db.events_of(gid)), "event") + " on or coming up",
                   "Weekly champions are " + ("on" if weekly.champions_on(db, gid) else "off"),
                   "Staff report is " + ("on" if db.get_premium_setting(gid, "report_on") else "off")],
        "welcome": [_count(len(db.autoroles_of(gid)), "autorole"),
                    "Welcome messages are " + ("on" if guild.get_channel(
                        db.greeting(gid, "welcome")["channel_id"]) else "off"),
                    "Goodbye messages are " + ("on" if guild.get_channel(
                        db.greeting(gid, "goodbye")["channel_id"]) else "off")],
    }


# ------------------------------------------------------------------ gacha

def gacha_state(bot, guild) -> dict:
    db = bot.db
    gid = guild.id
    listed, sections = set(), []
    for title, keys in GACHA_SECTIONS:
        fields = []
        for key in keys:
            if key in config.GUILD_SETTINGS:
                listed.add(key)
                fields.append(_setting(db, gid, key))
        sections.append({"title": title, "fields": fields})
    rest = [_setting(db, gid, k) for k in config.GUILD_SETTINGS if k not in listed]
    if rest:
        sections.append({"title": "Other", "fields": rest})
    return {
        "prefix": db.get_prefix(gid) or "",
        "default_prefix": config.PREFIX,
        "sections": sections,
        # Switches the bot really acts on; the rest are only recorded.
        "toggles": [{"group": group, "items": [
            {"key": key, "label": desc, "on": bool(db.get_toggle(gid, key, default))}
            for key, (default, g, desc, live) in TOGGLES.items() if g == group and live]}
            for group in GROUPS],
        "colour": f"#{db.get_pref(gid, 'cardcolour', config.CARD_COLOUR):06X}",
        "allowed": [str(c) for c in db.allowed_channels(gid)],
        "channels": _channels(guild),
    }


def _setting(db, gid, key):
    default, low, high, label = config.GUILD_SETTINGS[key]
    switch = low == 0 and high == 1
    low, high = db.setting_range(gid, key)
    return {"key": key, "value": db.get_setting(gid, key), "default": default,
            "min": low, "max": high, "label": label, "switch": switch,
            "more": premium.more_room(key, db.plan_rank(gid))}


def gacha_save(bot, guild, body) -> list:
    db = bot.db
    problems = []
    settings = body.get("settings") or {}
    clean = {}
    for key, value in settings.items():
        if key not in config.GUILD_SETTINGS:
            problems.append(f"There's no setting called {key}.")
            continue
        label = config.GUILD_SETTINGS[key][3]
        low, high = db.setting_range(guild.id, key)
        number = _id(value)
        if number is None or not low <= number <= high:
            more = premium.more_room(key, db.plan_rank(guild.id))
            problems.append(f"{label}: pick from {low:,} to {high:,}."
                            + (f" {more}." if more else ""))
        else:
            clean[key] = number

    toggles = {}
    for key, value in (body.get("toggles") or {}).items():
        if key in TOGGLES and TOGGLES[key][3]:
            toggles[key] = 1 if value else 0

    prefix = body.get("prefix")
    if prefix is not None:
        prefix = str(prefix).strip()
        if len(prefix) > 5 or (prefix and any(c.isspace() for c in prefix)):
            problems.append("The prefix is 1 to 5 characters, with no spaces."
                            " Leave it empty for the default.")

    colour = body.get("colour")
    if colour is not None:
        try:
            colour = int(str(colour).lstrip("#"), 16)
            if not 0 <= colour <= 0xFFFFFF:
                raise ValueError
        except ValueError:
            problems.append("The card colour has to be a colour like #7C6BF0.")

    allowed = body.get("allowed")
    channel_ids = []
    if allowed is not None:
        for value in allowed if isinstance(allowed, list) else []:
            channel = _text_channel(guild, value)
            if channel:
                channel_ids.append(channel.id)

    if problems:
        return problems
    for key, value in clean.items():
        db.set_setting(guild.id, key, value)
    for key, value in toggles.items():
        db.set_toggle(guild.id, key, value)
    if prefix is not None:
        if prefix and prefix != config.PREFIX:
            db.set_prefix(guild.id, prefix)
        else:
            db.clear_prefix(guild.id)
    if colour is not None:
        db.set_pref(guild.id, "cardcolour", colour)
    if allowed is not None:
        db.clear_allowed_channels(guild.id)
        for channel_id in channel_ids:
            db.allow_channel(guild.id, channel_id)
    return []


# ------------------------------------------------------------- moderation

def mod_state(bot, guild) -> dict:
    db = bot.db
    gid = guild.id
    return {
        "ready": bool(db.get_mod_config(gid, "jail_role")),
        "jail_channel": str(db.get_mod_config(gid, "jail_channel") or ""),
        "log_channel": str(db.get_mod_config(gid, "log_channel") or ""),
        "lock_role": str(db.get_mod_config(gid, "lock_role") or ""),
        "staff_roles": [str(r) for r in db.staff_roles_of(gid)],
        "punishments": [{"threshold": r["threshold"], "action": r["action"],
                         "duration": describe_duration(r["duration"])
                         if r["duration"] else ""}
                        for r in db.warn_punishments_of(gid)],
        "lockdown_ignored": [str(c) for c in db.lockdown_ignored(gid)],
        "actions": list(PUNISHMENTS),
        "channels": _channels(guild),
        "roles": _roles(guild),
        "premium": db.is_premium(gid),
        "plus": db.has_feature(gid, "warn_punishments"),
        "free_punishments": FREE_WARN_PUNISHMENTS,
        "automod": {
            "settings": automod_cog.settings_of(db, gid),
            "filters": [{"key": k, "name": n, "what": w, "premium": p}
                        for k, (n, w, p, _a) in automod_cog.FILTERS.items()],
            "actions": list(automod_cog.ACTIONS),
            "numbers": {k: {"min": lo, "max": hi}
                        for k, (_d, lo, hi) in automod_cog.NUMBERS.items()},
            "words": "\n".join(db.automod_words(gid)),
            "exempt": [str(c) for c in db.automod_exempt(gid)],
        },
    }


def mod_save(bot, guild, body) -> list:
    db = bot.db
    problems = []

    log = body.get("log_channel")
    log_channel = None
    if log is not None and log != "":
        log_channel = _text_channel(guild, log)
        if not log_channel:
            problems.append("Pick a text channel in this server for the mod log.")

    lock = body.get("lock_role")
    lock_role = None
    if lock:
        lock_role = guild.get_role(_id(lock)) if _id(lock) else None
        if not lock_role or lock_role.is_default():
            problems.append("Pick a role in this server for lockdowns, or"
                            " @everyone.")

    staff = []
    for value in body.get("staff_roles") or []:
        role = guild.get_role(_id(value)) if _id(value) else None
        if role and not role.is_default():
            staff.append(role.id)

    rows = []
    seen = set()
    for row in (body.get("punishments") or [])[:MAX_ROWS]:
        threshold = _id(row.get("threshold"))
        action = str(row.get("action", "")).lower()
        if threshold is None or not 1 <= threshold <= 50:
            problems.append("Warn punishments start at 1 to 50 warnings.")
            continue
        if threshold in seen:
            problems.append(f"There are two punishments at {threshold} warnings.")
            continue
        if action not in PUNISHMENTS:
            problems.append(f"At {threshold} warnings: pick timeout, jail,"
                            " kick or ban.")
            continue
        seconds = 0
        if action == "timeout":
            seconds = parse_duration(str(row.get("duration") or "1h"))
            if not seconds or seconds > 28 * 86400:
                problems.append(f"At {threshold} warnings: a timeout like 10m,"
                                " 1h or 1d, up to 28d.")
                continue
        seen.add(threshold)
        rows.append((threshold, action, seconds))

    if len(rows) > FREE_WARN_PUNISHMENTS and not db.has_feature(guild.id, "warn_punishments"):
        problems.append(f"Free servers can have {FREE_WARN_PUNISHMENTS} warn"
                        f" punishments. {premium.needs('warn_punishments')} allows up to 50.")

    ignored = []
    for value in body.get("lockdown_ignored") or []:
        channel = _text_channel(guild, value)
        if channel:
            ignored.append(channel.id)

    auto = body.get("automod")
    auto_changes, auto_words, auto_exempt = {}, None, None
    if isinstance(auto, dict):
        smarter = db.has_feature(guild.id, "automod")
        for key, (name, _w, paid, _a) in automod_cog.FILTERS.items():
            row = (auto.get("filters") or {}).get(key)
            if not isinstance(row, dict):
                continue
            on = bool(row.get("on"))
            if on and paid and not smarter:
                problems.append(f"The {name.lower()} filter comes with Premium.")
            action = str(row.get("action", "")).lower()
            if action not in automod_cog.ACTIONS:
                problems.append(f"Pick what happens after the {name.lower()} filter.")
                continue
            auto_changes[f"{key}_on"] = 1 if on else 0
            auto_changes[f"{key}_action"] = action
        for key, (_d, low, high) in automod_cog.NUMBERS.items():
            if key in auto:
                n = _id(auto[key])
                if n is None or not low <= n <= high:
                    problems.append(f"Automod numbers: pick from {low} to {high}.")
                else:
                    auto_changes[key] = n
        if "words" in auto:
            auto_words = automod_cog.clean_words(str(auto["words"] or ""))
        if "exempt" in auto:
            auto_exempt = [c.id for c in (_text_channel(guild, v) for v in auto["exempt"] or [])
                           if c]

    if problems:
        return problems
    gid = guild.id
    for key, value in auto_changes.items():
        db.set_automod(gid, key, value)
    if auto_words is not None:
        db.replace_automod_words(gid, auto_words)
    if auto_exempt is not None:
        db.replace_automod_exempt(gid, auto_exempt)
    if log is not None:
        db.set_mod_config(gid, "log_channel", log_channel.id if log_channel else 0)
    if lock is not None:
        db.set_mod_config(gid, "lock_role", lock_role.id if lock_role else 0)
    if body.get("staff_roles") is not None:
        for role_id in db.staff_roles_of(gid):
            db.remove_staff_role(gid, role_id)
        for role_id in staff:
            db.add_staff_role(gid, role_id)
    if body.get("punishments") is not None:
        for row in db.warn_punishments_of(gid):
            db.remove_warn_punishment(gid, row["threshold"])
        for threshold, action, seconds in rows:
            db.set_warn_punishment(gid, threshold, action, seconds)
    if body.get("lockdown_ignored") is not None:
        for channel_id in db.lockdown_ignored(gid):
            db.unignore_lockdown(gid, channel_id)
        for channel_id in ignored:
            db.ignore_lockdown(gid, channel_id)
    return []


# ------------------------------------------------------------------ voice

def voice_state(bot, guild) -> dict:
    db = bot.db
    gid = guild.id
    create = db.get_vc_setting(gid, "create_channel")
    return {
        "create_channel": str(create) if guild.get_channel(create) else "",
        "hour_roles": [{"hours": r["hours"], "role": str(r["role_id"])}
                       for r in db.hour_roles_of(gid)],
        "voice_channels": _channels(guild, discord.VoiceChannel),
        "roles": _roles(guild),
    }


def voice_save(bot, guild, body) -> list:
    db = bot.db
    problems = []
    create = body.get("create_channel")
    create_channel = None
    if create:
        channel = guild.get_channel(_id(create)) if _id(create) else None
        if not isinstance(channel, discord.VoiceChannel):
            problems.append("Pick a voice channel for Join To Create.")
        create_channel = channel

    rows, seen = [], set()
    for row in (body.get("hour_roles") or [])[:MAX_ROWS]:
        hours = _id(row.get("hours"))
        role = _usable_role(guild, row.get("role"))
        if hours is None or not 1 <= hours <= 100_000:
            problems.append("Hour roles need a number of hours above 0.")
        elif hours in seen:
            problems.append(f"{hours} hours has two roles. Pick one.")
        elif not role:
            problems.append(f"The role at {hours} hours has to be one I can"
                            " give: below my own role, not another bot's.")
        else:
            seen.add(hours)
            rows.append((hours, role.id))

    if problems:
        return problems
    gid = guild.id
    if create is not None:
        if create_channel:
            db.set_vc_setting(gid, "create_channel", create_channel.id)
        else:
            db.clear_vc_settings(gid)
    if body.get("hour_roles") is not None:
        for row in db.hour_roles_of(gid):
            db.remove_hour_role(gid, row["hours"])
        for hours, role_id in rows:
            db.set_hour_role(gid, hours, role_id)
    return []


# ------------------------------------------------------ Premium extras

def extras_state(bot, guild) -> dict:
    db = bot.db
    gid = guild.id
    get = db.get_premium_setting
    now = time.time()
    return {
        "premium": db.is_premium(gid),
        "plus": db.has_feature(gid, "events"),
        "events": [{"id": e["id"], "kind": e["kind"], "strength": e["strength"],
                    "starts_at": e["starts_at"], "ends_at": e["ends_at"],
                    "running": e["starts_at"] <= now,
                    "label": events_cog.describe(e["kind"], e["strength"])}
                   for e in db.events_of(gid)],
        "kinds": [{"key": k, "name": n, "default": d, "min": lo, "max": hi, "unit": u}
                  for k, (n, _e, d, lo, hi, u) in events_cog.KINDS.items()],
        "background": bool(db.rank_background(gid, 0)),
        "champ_channel": str(get(gid, "champ_channel") or ""),
        "champ_chat_role": str(get(gid, "champ_chat_role") or ""),
        "champ_voice_role": str(get(gid, "champ_voice_role") or ""),
        "report_on": bool(get(gid, "report_on")),
        "profile": botprofile.state(bot, guild),
        "channels": _channels(guild),
        "roles": _roles(guild),
    }


def extras_save(bot, guild, body) -> list:
    """Champions and the staff report. Events and the card background have
    buttons of their own, which act at once."""
    db = bot.db
    gid = guild.id
    problems = []
    plus = db.has_feature(gid, "champions")
    channel = None
    if body.get("champ_channel"):
        channel = _text_channel(guild, body["champ_channel"])
        if not channel:
            problems.append("Pick a text channel for the champions.")
    roles = {}
    for kind in ("chat", "voice"):
        value = body.get(f"champ_{kind}_role")
        if value:
            role = _usable_role(guild, value)
            if not role:
                problems.append(f"The {kind} champion role has to be one I can give.")
            roles[kind] = role
    wants = bool(channel or any(roles.values()) or body.get("report_on"))
    if wants and not plus:
        problems.append("Champions and the staff report come with"
                        f" {premium.needs('champions')}.")
    if problems:
        return problems
    was_on = weekly.champions_on(db, gid)
    db.set_premium_setting(gid, "champ_channel", channel.id if channel else 0)
    for kind in ("chat", "voice"):
        role = roles.get(kind)
        db.set_premium_setting(gid, f"champ_{kind}_role", role.id if role else 0)
    if weekly.champions_on(db, gid) and not was_on:
        db.set_premium_setting(gid, "champ_week", weekly.week_now())
    report = bool(body.get("report_on"))
    if report and not db.get_premium_setting(gid, "report_on"):
        db.set_premium_setting(gid, "report_week", weekly.week_now())
    db.set_premium_setting(gid, "report_on", 1 if report else 0)
    return []


# ------------------------------------------------------ welcome & roles

def welcome_state(bot, guild) -> dict:
    db = bot.db
    gid = guild.id
    greetings = {}
    for kind in serversetup.KINDS:
        row = db.greeting(gid, kind)
        greetings[kind] = {
            "channel": str(row["channel_id"]) if guild.get_channel(row["channel_id"]) else "",
            "message": row["message"] or serversetup.DEFAULTS[kind],
            "embed": bool(row["embed"]),
        }
    return {
        "autoroles": [str(r) for r in db.autoroles_of(gid)],
        "greetings": greetings,
        "defaults": serversetup.DEFAULTS,
        "variables": list(serversetup.VARIABLES),
        "message_limit": serversetup.MESSAGE_LIMIT,
        "max_autoroles": serversetup.MAX_AUTOROLES,
        "channels": _channels(guild),
        "roles": _roles(guild),
    }


def welcome_save(bot, guild, body) -> list:
    db = bot.db
    gid = guild.id
    problems = []
    roles = []
    for value in (body.get("autoroles") or [])[:MAX_ROWS]:
        role = _usable_role(guild, value)
        if not role:
            problems.append("Autoroles have to be roles I can give: below my own role,"
                            " not another bot's.")
        elif role not in roles:
            roles.append(role)
    if len(roles) > serversetup.MAX_AUTOROLES:
        problems.append(f"Up to {serversetup.MAX_AUTOROLES} autoroles.")
    greetings = {}
    for kind in serversetup.KINDS:
        given = (body.get("greetings") or {}).get(kind)
        if given is None:
            continue
        channel = None
        if given.get("channel"):
            channel = _text_channel(guild, given["channel"])
            if not channel:
                problems.append(f"Pick a text channel for {kind} messages.")
        message = str(given.get("message") or "").strip()
        if len(message) > serversetup.MESSAGE_LIMIT:
            problems.append(f"Keep the {kind} message under {serversetup.MESSAGE_LIMIT}"
                            " characters.")
        if message == serversetup.DEFAULTS[kind]:
            message = ""            # the default, so a better default reaches it later
        greetings[kind] = {"channel_id": channel.id if channel else 0, "message": message,
                           "embed": 1 if given.get("embed") else 0}
    if problems:
        return problems
    if body.get("autoroles") is not None:
        db.replace_autoroles(gid, [r.id for r in roles])
    for kind, fields in greetings.items():
        db.set_greeting(gid, kind, **fields)
    return []


PARTS = {
    "gacha": (gacha_state, gacha_save),
    "mod": (mod_state, mod_save),
    "voice": (voice_state, voice_save),
    "welcome": (welcome_state, welcome_save),
    "extras": (extras_state, extras_save),
}
