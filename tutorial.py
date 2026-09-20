"""The tutorial: what the steps are, and what finishing one is worth.

Built the way Mudae's is. A step holds several substeps; they can be done in
any order, and the step is only finished when every one of them is. Finishing
a step pays a reward and opens the next.

Two rules worth stating because they are easy to get wrong:

Substeps are not credited before you reach their step. Doing something in
step 2 that happens to be a substep of step 9 does not tick it off in
advance - you do it again when you get there. This is Mudae's behaviour and
it is the right one: the tutorial is a sequence of things to learn, not a
checklist to be back-filled.

A substep is finished by *using the command*, not by asking for it. Some also
carry a `check`, for the ones where using the command is not the point -
claiming a character, or holding a balance.

`commands` names primary command names; an alias resolves to its primary, so
$w and $waifu and $roll all satisfy the same substep.
"""

# reward keys: karuda, item, keys, wish_slot, rolls, badge


def _with_args(*names):
    """The command had to be given something.

    Without this, "type $help" and "type $help <command>" are the same
    keystroke as far as the listener is concerned, and one $help would tick
    off both.
    """
    def wanted(ctx):
        return any(ctx.kwargs.get(name) for name in names)
    return wanted


def _owns(count):
    return lambda db, gid, uid: db.harem_size(gid, uid) >= count


def _balance(amount):
    return lambda db, gid, uid: db.get_player(gid, uid)["karuda"] >= amount


def _wishes(count):
    return lambda db, gid, uid: len(db.wishes_of(gid, uid)) >= count


def _likes(count):
    return lambda db, gid, uid: len(db.likes_of(gid, uid)) >= count


def _notes(count):
    return lambda db, gid, uid: len(db.notes_of(gid, uid)) >= count


def _tower(floor):
    return lambda db, gid, uid: db.get_player(gid, uid)["tower_floor"] >= floor


STEPS = [
    {
        "title": "COLLECT YOUR FIRST CHARACTER",
        "reward": {"karuda": 200},
        "substeps": [
            {
                "key": "roll",
                "title": "ROLL A CHARACTER",
                "text": "Type `{p}w` for a woman or `{p}h` for a man. This is"
                        " called a roll.\nAdd `a` for anime only (`{p}wa`) or"
                        " `g` for games (`{p}wg`).\nUse `{p}m` if you have no"
                        " preference.",
                "commands": {"roll", "waifu", "husbando", "wa", "wg", "ha",
                             "hg", "ma", "mg"},
            },
            {
                "key": "claim",
                "title": "CLAIM ONE",
                "text": "Press the **Claim** button under a roll.\nA character"
                        " belongs to one person per server, and you get one"
                        " claim every few hours.",
                "commands": set(),
                "check": _owns(1),
                "skippable": True,
            },
            {
                "key": "harem",
                "title": "CHECK WHAT YOU HAVE",
                "text": "Type `{p}mm` to flip through everyone you own.\nThis"
                        " list belongs to this server only.",
                "commands": {"harem"},
            },
        ],
    },
    {
        "title": "FIND THINGS IN THE DATABASE",
        "reward": {"item": "greentea"},
        "substeps": [
            {
                "key": "im",
                "title": "LOOK UP A CHARACTER",
                "text": "Type `{p}im <name>` — for example `{p}im asuna`.\n"
                        "Never type the `<` and `>`; they only mean"
                        " “put something here”.",
                "commands": {"info"},
            },
            {
                "key": "series",
                "title": "LOOK UP A SERIES",
                "text": "Type `{p}series <name>` to see everyone in it, best"
                        " known first.",
                "commands": {"series"},
            },
            {
                "key": "search",
                "title": "SEARCH BY NAME",
                "text": "Type `{p}search <text>` when you only remember part"
                        " of a name.",
                "commands": {"search"},
            },
            {
                "key": "wish",
                "title": "WISH FOR SOMEBODY",
                "text": "Type `{p}wish <name>`. When they roll anywhere here,"
                        " you get pinged — and you get a head start on the"
                        " claim.",
                "commands": {"wish"},
                "check": _wishes(1),
            },
        ],
    },
    {
        "title": "TIMERS AND MONEY",
        "reward": {"karuda": 200},
        "substeps": [
            {
                "key": "rolls",
                "title": "SEE WHAT YOU HAVE LEFT",
                "text": "Type `{p}rolls` for your rolls and every cooldown at"
                        " once.",
                "commands": {"rolls"},
            },
            {
                "key": "dk",
                "title": "TAKE YOUR DAILY",
                "text": "Type `{p}dk`. Two shards appear and you keep one —"
                        " choose carefully, because the other is left for"
                        " somebody else to snipe.",
                "commands": {"dk"},
            },
            {
                "key": "balance",
                "title": "CHECK YOUR KARUDA",
                "text": "Type `{p}k` to see what you are holding and which"
                        " shards you have collected.",
                "commands": {"balance"},
            },
            {
                "key": "shards",
                "title": "LEARN THE SHARDS",
                "text": "Type `{p}shards` for what each one pays and how rare"
                        " it is.",
                "commands": {"shards"},
            },
        ],
    },
    {
        "title": "GETTING HELP",
        "reward": {"wish_slot": 1},
        "substeps": [
            {
                "key": "tutoback",
                "title": "GO BACK A PAGE",
                "text": "Type `{p}tuto 1` to re-read an earlier step. Any step"
                        " you have reached can be read again.",
                "commands": {"tuto"},
            },
            {
                "key": "help",
                "title": "GET THE COMMAND LIST",
                "text": "Type `{p}help`. Every command is on it, and it comes"
                        " by DM so the channel stays clean.",
                "commands": {"help"},
            },
            {
                "key": "helpone",
                "title": "ASK ABOUT ONE COMMAND",
                "text": "Type `{p}help wish` for what a single command does,"
                        " what it takes and what else it answers to.",
                "commands": {"help"},
                "wants": _with_args("command"),
            },
            {
                "key": "wishlist",
                "title": "READ YOUR WISHLIST",
                "text": "Type `{p}wishlist`.",
                "commands": {"wishlist"},
            },
        ],
    },
    {
        "title": "PICTURES",
        "reward": {"karuda": 250},
        "substeps": [
            {
                "key": "album",
                "title": "FLIP THROUGH SOMEBODY'S ART",
                "text": "Type `{p}album <name>`, or use the arrows under"
                        " `{p}im`. Most characters have one picture; some have"
                        " several.",
                "commands": {"album", "info"},
            },
            {
                "key": "randomimg",
                "title": "GET A RANDOM PICTURE",
                "text": "Type `{p}randomimg <name>`.",
                "commands": {"randomimg"},
            },
            {
                "key": "imglist",
                "title": "SEE EVERY PICTURE AS LINKS",
                "text": "Type `{p}imglist <name>`.",
                "commands": {"imglist"},
            },
        ],
    },
    {
        "title": "NOTES",
        "reward": {"karuda": 250},
        "substeps": [
            {
                "key": "note",
                "title": "WRITE ON SOMEBODY YOU OWN",
                "text": "Type `{p}note`, pick one of yours, and write"
                        " something. It shows next to them in your harem.",
                "commands": {"note"},
                "check": _notes(1),
                "skippable": True,
            },
            {
                "key": "notelist",
                "title": "READ YOUR NOTES BACK",
                "text": "Type `{p}notelist`.",
                "commands": {"notelist"},
            },
            {
                "key": "notesearch",
                "title": "SEARCH YOUR NOTES",
                "text": "Type `{p}notesearch <text>`. Notes are worth writing"
                        " because you can find things by them later.",
                "commands": {"notesearch"},
            },
        ],
    },
    {
        "title": "THE TOY BOX",
        "reward": {"item": "mixtea"},
        "substeps": [
            {
                "key": "fate",
                "title": "ASK FATE A QUESTION",
                "text": "Type `{p}fate <your question>`.",
                "commands": {"fate"},
            },
            {
                "key": "quote",
                "title": "GET SOMETHING WISE-SOUNDING",
                "text": "Type `{p}quote`.",
                "commands": {"quote"},
            },
            {
                "key": "beam",
                "title": "BEAM SOMETHING AWAY",
                "text": "Type `{p}beam`, or `{p}destroy <anything>`.",
                "commands": {"beam", "destroy"},
            },
            {
                "key": "poem",
                "title": "MAKE A POEM",
                "text": "Type `{p}poem`. It will not be good.",
                "commands": {"poem"},
            },
        ],
    },
    {
        "title": "TEA",
        "reward": {"karuda": 250},
        "substeps": [
            {
                "key": "tea",
                "title": "OPEN THE CUPBOARD",
                "text": "Type `{p}tea` to see what you are holding and what"
                        " each one does.",
                "commands": {"tea"},
            },
            {
                "key": "drinktea",
                "title": "DRINK ONE",
                "text": "`{p}greentea` is three more rolls, `{p}blacktea`"
                        " clears your claim wait, `{p}redtea` is karuda,"
                        " `{p}yellowtea` is a key.\nThey turn up in the daily"
                        " drop, and `{p}buytea` buys one.",
                "commands": {"greentea", "blacktea", "redtea", "yellowtea",
                             "mixtea"},
            },
            {
                "key": "buytea",
                "title": "VISIT THE SHOP",
                "text": "Type `{p}shop` to see what karuda buys.",
                "commands": {"shop", "buytea"},
            },
        ],
    },
    {
        "title": "NICKNAMES AND LIKES",
        "reward": {"karuda": 300},
        "substeps": [
            {
                "key": "myalias",
                "title": "TEACH A NICKNAME",
                "text": "Type `{p}myalias <character> | <nickname>`.\nAfter"
                        " that `{p}im <nickname>` finds them. Yours is private;"
                        " `{p}alias` teaches one the whole server shares.",
                "commands": {"myalias", "alias"},
            },
            {
                "key": "alist",
                "title": "SEE THE NICKNAMES",
                "text": "Type `{p}myalist` for yours, `{p}alist` for the"
                        " server's.",
                "commands": {"myalist", "alist"},
            },
            {
                "key": "like",
                "title": "LIKE SOMEBODY",
                "text": "Type `{p}like <name>`. Anyone can like anyone — you"
                        " do not have to own them.",
                "commands": {"like"},
                "check": _likes(1),
            },
            {
                "key": "likelist",
                "title": "READ YOUR LIKES BACK",
                "text": "Type `{p}likelist`.",
                "commands": {"likelist"},
            },
        ],
    },
    {
        "title": "LEADERBOARDS",
        "reward": {"karuda": 300},
        "substeps": [
            {
                "key": "topchars",
                "title": "SEE THE BEST CHARACTERS",
                "text": "Type `{p}topchars`. Page one is the top ten, page ten"
                        " is ninety-one to a hundred.\n`{p}topchars <series>`"
                        " ranks inside one series.",
                "commands": {"topchars"},
            },
            {
                "key": "top",
                "title": "SEE THE BIGGEST HAREMS",
                "text": "Type `{p}top`.",
                "commands": {"top", "topclaims"},
            },
            {
                "key": "topseries",
                "title": "SEE WHAT THIS SERVER LIKES",
                "text": "Type `{p}topseries` — what people here actually"
                        " claim, which is rarely what is popular globally.",
                "commands": {"topseries"},
            },
            {
                "key": "serveroverview",
                "title": "SEE THE WHOLE SERVER",
                "text": "Type `{p}serveroverview`.",
                "commands": {"serveroverview"},
            },
        ],
    },
    {
        "title": "PERKS THAT LAST",
        "reward": {"karuda": 300},
        "substeps": [
            {
                "key": "badges",
                "title": "SEE THE BADGES",
                "text": "Type `{p}badges`. These are bought once and keep"
                        " paying.",
                "commands": {"badges"},
            },
            {
                "key": "profile",
                "title": "CHECK YOUR PROFILE",
                "text": "Type `{p}profile`.",
                "commands": {"profile"},
            },
            {
                "key": "perks",
                "title": "ADD IT ALL UP",
                "text": "Type `{p}perks` to see everything you have earned"
                        " working together.",
                "commands": {"perks"},
            },
            {
                "key": "save",
                "title": "SAVE UP",
                "text": "Hold **1,000** karuda at once. Rolling already-owned"
                        " characters and `{p}dk` are the quick ways.",
                "commands": set(),
                "check": _balance(1000),
            },
        ],
    },
    {
        "title": "OTHER PEOPLE",
        "reward": {"keys": 1},
        "substeps": [
            {
                "key": "myid",
                "title": "FIND YOUR ID",
                "text": "Type `{p}myid`.",
                "commands": {"myid"},
            },
            {
                "key": "avatar",
                "title": "SHOW SOMEBODY'S AVATAR",
                "text": "Type `{p}avatar @someone`.",
                "commands": {"avatar"},
            },
            {
                "key": "otherharem",
                "title": "LOOK AT SOMEBODY ELSE'S HAREM",
                "text": "Type `{p}mm @someone`.",
                "commands": {"harem", "haremlist"},
            },
            {
                "key": "pay",
                "title": "SEND SOMEBODY KARUDA",
                "text": "Type `{p}pay @someone <amount>`.",
                "commands": {"pay"},
            },
        ],
    },
    {
        "title": "NARROWING THE POOL",
        "reward": {"karuda": 400},
        "substeps": [
            {
                "key": "toggles",
                "title": "SEE THE SWITCHES",
                "text": "Type `{p}toggles`. These decide what can roll here.",
                "commands": {"toggles"},
            },
            {
                "key": "togglewestern",
                "title": "TRY A SWITCH",
                "text": "Type `{p}togglegames` to stop game characters"
                        " rolling, or `{p}togglewestern` for cartoons.\nIt is"
                        " a toggle — type it again to put it back.",
                "commands": {"togglegames", "togglewestern", "toggleirl",
                             "togglehentai"},
            },
            {
                "key": "disablelist",
                "title": "SEE WHAT IS SWITCHED OFF",
                "text": "Type `{p}disablelist`.",
                "commands": {"disablelist"},
            },
        ],
    },
    {
        "title": "MAKING IT YOURS",
        "reward": {"karuda": 400},
        "substeps": [
            {
                "key": "settings",
                "title": "SEE EVERY DIAL",
                "text": "Type `{p}settings`.",
                "commands": {"settings"},
            },
            {
                "key": "preset",
                "title": "READ THE PRESETS",
                "text": "Type `{p}preset`. One command sets five dials —"
                        " relaxed, normal or slow.",
                "commands": {"preset"},
            },
            {
                "key": "sortmarry",
                "title": "CHOOSE HOW YOUR HAREM SORTS",
                "text": "Type `{p}sortmarry karuda`, or `likes`, `name`,"
                        " `recent`.",
                "commands": {"sortmarry"},
            },
            {
                "key": "rollbias",
                "title": "TURN A DIAL YOURSELF",
                "text": "Type `{p}set roll_bias 35`. It decides how often a"
                        " famous character turns up out of a hundred thousand"
                        " — 0 is a flat lottery, 100 is mostly faces you"
                        " know. Needs Manage Server.",
                "commands": {"set"},
            },
        ],
    },
    {
        "title": "TRADING",
        "reward": {"karuda": 400},
        "substeps": [
            {
                "key": "trade",
                "title": "OFFER A TRADE",
                "text": "Type `{p}trade @someone`. Both sides pick from a menu"
                        " — there is nothing to type out.",
                "commands": {"trade"},
            },
            {
                "key": "gift",
                "title": "GIVE SOMEBODY A CHARACTER",
                "text": "Type `{p}gift @someone` if you just want to hand one"
                        " over.",
                "commands": {"gift"},
            },
            {
                "key": "firstmarry",
                "title": "PICK YOUR SHOWCASE",
                "text": "Type `{p}fm <name>` to put one of yours at the top of"
                        " your profile.",
                "commands": {"firstmarry"},
            },
        ],
    },
    {
        "title": "BONDS",
        "reward": {"karuda": 500},
        "substeps": [
            {
                "key": "setsoulmate",
                "title": "NAME A SOULMATE",
                "text": "Type `{p}setsoulmate` and pick one of yours. It pays"
                        " a small bonus, and it says something.",
                "commands": {"setsoulmate"},
                "skippable": True,
            },
            {
                "key": "keys",
                "title": "CHECK YOUR KEYS",
                "text": "Type `{p}keys`. A key raises one character's value"
                        " for good.",
                "commands": {"keys"},
            },
            {
                "key": "soulmates",
                "title": "SEE EVERYONE'S CHOICES",
                "text": "Type `{p}soulmates`.",
                "commands": {"soulmates"},
            },
        ],
    },
    {
        "title": "THE TOWER",
        "reward": {"karuda": 800, "badge": "graduate"},
        "substeps": [
            {
                "key": "tower",
                "title": "LOOK AT THE TOWER",
                "text": "Type `{p}kt`. Every floor costs more and pays"
                        " forever.",
                "commands": {"tower"},
            },
            {
                "key": "toptower",
                "title": "SEE WHO HAS CLIMBED HIGHEST",
                "text": "Type `{p}toptower`.",
                "commands": {"toptower"},
            },
            {
                "key": "climb",
                "title": "CLIMB YOUR FIRST FLOOR",
                "text": "Type `{p}ktup`. It is expensive on purpose.",
                "commands": {"ktup"},
                "check": _tower(1),
                "skippable": True,
            },
            {
                "key": "graduate",
                "title": "READ THE WHOLE LIST",
                "text": "Type `{p}help`. This tutorial covered a fraction of"
                        " it — everything else is on that page.",
                "commands": {"help"},
            },
        ],
    },
]

# Everything past this is a challenge rather than a lesson, which is what
# $skiptuto skips to.
MAIN_STEPS = len(STEPS)

STEPS += [
    {
        "title": "CHALLENGE — A REAL COLLECTION",
        "reward": {"karuda": 2000},
        "substeps": [
            {
                "key": "own20",
                "title": "OWN 20 CHARACTERS",
                "text": "Then type `{p}mm`.",
                "commands": {"harem"},
                "check": _owns(20),
            },
            {
                "key": "wish10",
                "title": "WISH FOR 10",
                "text": "Then type `{p}wishlist`.",
                "commands": {"wishlist"},
                "check": _wishes(10),
            },
            {
                "key": "like10",
                "title": "LIKE 10 CHARACTERS",
                "text": "Then type `{p}likelist`.",
                "commands": {"likelist"},
                "check": _likes(10),
            },
        ],
    },
    {
        "title": "CHALLENGE — RICH",
        "reward": {"karuda": 5000},
        "substeps": [
            {
                "key": "rich",
                "title": "HOLD 25,000 KARUDA AT ONCE",
                "text": "Then type `{p}k`.",
                "commands": {"balance"},
                "check": _balance(25000),
            },
            {
                "key": "badgeowner",
                "title": "OWN A BADGE",
                "text": "Then type `{p}badges`.",
                "commands": {"badges"},
                "check": lambda db, gid, uid: bool(db.badges_of(gid, uid)),
            },
            {
                "key": "floor3",
                "title": "REACH TOWER FLOOR 3",
                "text": "Then type `{p}kt`.",
                "commands": {"tower"},
                "check": _tower(3),
            },
        ],
    },
    {
        "title": "CHALLENGE — THE LAST ONE",
        "reward": {"karuda": 10000, "badge": "perfect"},
        "substeps": [
            {
                "key": "own100",
                "title": "OWN 100 CHARACTERS",
                "text": "Then type `{p}mm`.",
                "commands": {"harem"},
                "check": _owns(100),
            },
            {
                "key": "floor10",
                "title": "REACH TOWER FLOOR 10",
                "text": "Then type `{p}kt`.",
                "commands": {"tower"},
                "check": _tower(10),
            },
            {
                "key": "notes25",
                "title": "WRITE 25 NOTES",
                "text": "Then type `{p}notelist`.",
                "commands": {"notelist"},
                "check": _notes(25),
            },
        ],
    },
]

TOTAL_STEPS = len(STEPS)
TOTAL_SUBSTEPS = sum(len(step["substeps"]) for step in STEPS)


def step(number: int) -> dict:
    """One step, 1-based."""
    return STEPS[max(1, min(number, TOTAL_STEPS)) - 1]


def substeps_for(number: int) -> list:
    return step(number)["substeps"]


def describe_reward(reward: dict) -> str:
    import config

    parts = []
    if reward.get("karuda"):
        parts.append(f"**{reward['karuda']:,}** {config.CURRENCY}")
    if reward.get("item"):
        parts.append(f"one **{reward['item']}**")
    if reward.get("keys"):
        parts.append(f"**{reward['keys']}** key")
    if reward.get("wish_slot"):
        parts.append(f"**+{reward['wish_slot']}** wishlist slot")
    if reward.get("rolls"):
        parts.append(f"**+{reward['rolls']}** rolls")
    if reward.get("badge"):
        parts.append(f"the **{reward['badge']}** mark")
    return ", ".join(parts) if parts else "nothing but pride"
