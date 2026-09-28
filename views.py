"""Reusable interactive views: page flipping and yes/no confirmation."""
import copy
import difflib

import discord

import utils


class Paginator(discord.ui.View):
    """Flips through a prebuilt list of embeds. Only the invoker may click."""

    def __init__(self, embeds, owner_id: int, timeout: float = 120, art=None):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        # One image source per page, for characters whose art travels with
        # the bot instead of living on a CDN. A fresh file is built on every
        # flip because a discord.File is spent by the send that uses it.
        self.art = list(art) if art else [None] * len(embeds)
        self.owner_id = owner_id
        self.index = 0
        self.message = None
        if len(embeds) < self.JUMP_FROM:
            self.remove_item(self.first)
            self.remove_item(self.last)
        self._sync_labels()
        if len(embeds) == 1:
            self.clear_items()

    # Below this, jumping to an end is the same as pressing an arrow, and two
    # extra buttons on a two page flip is clutter.
    JUMP_FROM = 4

    def _sync_labels(self):
        self.page_label.label = f"{self.index + 1}/{len(self.embeds)}"
        at_start = self.index == 0
        at_end = self.index >= len(self.embeds) - 1
        self.prev.disabled = at_start
        self.next.disabled = at_end
        self.first.disabled = at_start
        self.last.disabled = at_end

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Run the command yourself to flip pages.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    async def _show(self, interaction: discord.Interaction):
        self._sync_labels()
        attachment = utils.art_file(self.art[self.index])
        # Passed explicitly either way: leaving it out keeps whatever the
        # previous page attached, so a page with no file of its own would
        # still be showing the last one.
        await interaction.response.edit_message(
            embed=self.embeds[self.index], view=self,
            attachments=[attachment] if attachment else [],
        )

    @discord.ui.button(label="⏮", style=discord.ButtonStyle.secondary)
    async def first(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = 0
        await self._show(interaction)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        await self._show(interaction)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.secondary, disabled=True)
    async def page_label(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        pass

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.embeds) - 1, self.index + 1)
        await self._show(interaction)

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.secondary)
    async def last(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = len(self.embeds) - 1
        await self._show(interaction)

    async def start(self, ctx):
        attachment = utils.art_file(self.art[0])
        self.message = await ctx.send(
            embed=self.embeds[0], view=self,
            **({"file": attachment} if attachment else {}),
        )
        return self.message


def _plain(text: str) -> str:
    """Lowercase letters and digits only, so punctuation never blocks a match."""
    return "".join(c for c in (text or "").lower() if c.isalnum())


def rank_matches(rows, query: str) -> list:
    """The rows worth showing for what has been typed, closest first.

    A dropdown of a hundred characters is a wall to read, so typing narrows
    it. What counts as closest, in order: the name starts with it, a word of
    the name starts with it, the name contains it, the series matches, and
    finally a misspelling close enough that difflib recognises it - which is
    what catches "hatsne" for Hatsune.
    """
    wanted = _plain(query)
    if not wanted:
        return list(rows)

    scored = []
    for row in rows:
        name = _plain(row["name"])
        words = [_plain(word) for word in str(row["name"]).split()]
        series = _plain(row["series"] if "series" in row.keys() else "")

        if name.startswith(wanted):
            score = 0.0
        elif any(word.startswith(wanted) for word in words if word):
            score = 1.0
        elif wanted in name:
            score = 2.0
        elif series.startswith(wanted) or wanted in series:
            score = 3.0
        else:
            close = difflib.SequenceMatcher(None, wanted, name).ratio()
            # 0.68 keeps "hatsne" on Hatsune Miku (0.71) and drops
            # "sakurajima" from Makima (0.63), which is the nearest pair of
            # a real misspelling and a coincidence in the shipped roster.
            if close < 0.68:
                continue
            score = 4.0 + (1.0 - close)
        scored.append((score, str(row["name"]).lower(), row))

    scored.sort(key=lambda item: (item[0], item[1]))
    return [row for _score, _name, row in scored]


class CharacterSearch(discord.ui.Modal, title="Search"):
    """The box the picker types into."""

    term = discord.ui.TextInput(
        label="Part of a name",
        placeholder="ha  ->  Hatsune Miku, Hayase Nagatoro, ...",
        required=False,
        max_length=60,
    )

    def __init__(self, picker):
        super().__init__()
        self.picker = picker
        self.term.default = picker.query or None

    async def on_submit(self, interaction: discord.Interaction):
        await self.picker.search(interaction, str(self.term.value or ""))


class CharacterPicker(discord.ui.View):
    """A dropdown of somebody's harem, so a trade needs no typing.

    Discord allows 25 options in a select, and a harem can be longer, so the
    list pages. Only `owner_id` may touch it; everyone else gets told whose
    turn it is. When it finishes, `chosen` holds the picked row or None.
    """

    PER_PAGE = 25

    def __init__(self, rows, owner_id: int, placeholder: str, timeout: float = 120):
        super().__init__(timeout=timeout)
        # everything they own, and what is left after what they typed
        self.all_rows = list(rows)
        self.rows = list(rows)
        self.query = ""
        self.owner_id = owner_id
        self.placeholder = placeholder
        self.page = 0
        self.chosen = None
        self.cancelled = False
        self.message = None
        self._build()

    @property
    def pages(self) -> int:
        return max(1, -(-len(self.rows) // self.PER_PAGE))

    def apply_query(self, query: str):
        """Narrow the list to what was typed, and go back to the first page."""
        self.query = (query or "").strip()
        self.rows = rank_matches(self.all_rows, self.query)
        self.page = 0
        self._build()

    def _build(self):
        self.clear_items()
        start = self.page * self.PER_PAGE
        window = self.rows[start : start + self.PER_PAGE]

        if window:
            found = (f"{len(self.rows)} for \u201c{self.query}\u201d"
                     if self.query else f"{len(self.rows)} to choose from")
            select = discord.ui.Select(
                placeholder=f"{self.placeholder} ({found})",
                options=[
                    discord.SelectOption(
                        label=row["name"][:100],
                        value=str(row["id"]),
                        description=f"{row['series']}"[:100],
                    )
                    for row in window
                ],
            )
            select.callback = self._on_select
            self.add_item(select)
        else:
            # A select with no options is rejected by Discord, so say so on a
            # dead button rather than sending nothing back.
            empty = discord.ui.Button(
                label=f"Nobody matches \u201c{self.query}\u201d", disabled=True)
            self.add_item(empty)

        search = discord.ui.Button(
            label="Search" if not self.query else f"Search: {self.query}"[:80],
            emoji="\U0001f50d", row=1,
        )
        search.callback = self._on_search
        self.add_item(search)

        if self.query:
            clear = discord.ui.Button(label="Clear", row=1)
            clear.callback = self._on_clear
            self.add_item(clear)

        if self.pages > 1:
            previous = discord.ui.Button(label="◀", row=2)
            previous.disabled = self.page == 0
            previous.callback = self._on_prev
            self.add_item(previous)

            label = discord.ui.Button(
                label=f"{self.page + 1}/{self.pages}", row=2, disabled=True
            )
            self.add_item(label)

            nxt = discord.ui.Button(label="▶", row=2)
            nxt.disabled = self.page >= self.pages - 1
            nxt.callback = self._on_next
            self.add_item(nxt)

        cancel = discord.ui.Button(
            label="Cancel", style=discord.ButtonStyle.danger, row=2
        )
        cancel.callback = self._on_cancel
        self.add_item(cancel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                f"This is <@{self.owner_id}>'s turn to pick.", ephemeral=True
            )
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        character_id = int(interaction.data["values"][0])
        # Looked up in everything they own, not the filtered view: the
        # selection is made against the list on screen, but the row that
        # comes back should not depend on what was typed.
        self.chosen = next(
            (r for r in self.all_rows if r["id"] == character_id), None)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    async def _on_search(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CharacterSearch(self))

    async def search(self, interaction: discord.Interaction, query: str):
        self.apply_query(query)
        await interaction.response.edit_message(view=self)

    async def _on_clear(self, interaction: discord.Interaction):
        self.apply_query("")
        await interaction.response.edit_message(view=self)

    async def _on_prev(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self._build()
        await interaction.response.edit_message(view=self)

    async def _on_next(self, interaction: discord.Interaction):
        self.page = min(self.pages - 1, self.page + 1)
        self._build()
        await interaction.response.edit_message(view=self)

    async def _on_cancel(self, interaction: discord.Interaction):
        self.cancelled = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="Timed out.", view=None)
            except discord.HTTPException:
                pass


class Confirm(discord.ui.View):
    """Two-party confirmation, used by trades and gifts.

    `responders` is the set of user ids that must all accept. Any one of them
    declining kills the whole thing.
    """

    def __init__(self, responders, timeout: float = 90):
        super().__init__(timeout=timeout)
        self.responders = set(responders)
        self.accepted = set()
        self.declined_by = None
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.responders:
            await interaction.response.send_message(
                "This isn't your trade.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="Timed out.", view=None)
            except discord.HTTPException:
                pass

    def _finish(self):
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.accepted.add(interaction.user.id)
        if self.accepted >= self.responders:
            self._finish()
            await interaction.response.edit_message(view=self)
            self.stop()
        else:
            waiting = self.responders - self.accepted
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(
                "Waiting on " + ", ".join(f"<@{u}>" for u in waiting)
            )

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.declined_by = interaction.user.id
        self._finish()
        await interaction.response.edit_message(view=self)
        self.stop()


async def choose_character(ctx, rows, prompt: str, colour: int = 0x7C6BF0):
    """Pick one row from several. Returns the row, or None if they backed out.

    A single match is returned straight away - nobody should have to confirm
    a choice that was never ambiguous.
    """
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]

    view = CharacterPicker(rows, ctx.author.id, prompt)
    listing = "\n".join(
        f"**{row['name']}** · {row['series']}" for row in rows[:10]
    )
    if len(rows) > 10:
        listing += f"\n…and {len(rows) - 10} more"
    embed = discord.Embed(title="Which one?", description=listing, colour=colour)
    view.message = await ctx.send(embed=embed, view=view)
    await view.wait()
    return view.chosen


class DidYouMean(discord.ui.View):
    """Offers the command a typo was probably reaching for.

    The button re-runs the original message with the name corrected, so any
    arguments that were typed survive: "$harme gojou" becomes "$harem gojou"
    rather than a bare $harem.
    """

    def __init__(self, message, prefix: str, suggestion: str, rest: str,
                 owner_id: int, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.message = message
        self.prefix = prefix
        self.suggestion = suggestion
        self.rest = rest
        self.owner_id = owner_id
        self.sent = None
        self.run.label = f"{prefix}{suggestion}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "That one is not yours to answer.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        # The offer expires quietly rather than leaving a dead button.
        if self.sent:
            try:
                await self.sent.delete()
            except discord.HTTPException:
                pass

    @discord.ui.button(style=discord.ButtonStyle.primary)
    async def run(self, interaction: discord.Interaction,
                  button: discord.ui.Button):
        corrected = f"{self.prefix}{self.suggestion}{self.rest}"
        await interaction.response.edit_message(
            content=f"Running `{corrected}`", view=None
        )
        # A shallow copy with the content swapped: the real message carries
        # the author, channel and guild the command needs, and rebuilding
        # those by hand is how permissions checks get skipped by accident.
        echo = copy.copy(self.message)
        echo.content = corrected
        await interaction.client.process_commands(echo)

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def dismiss(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Never mind. `$help` lists everything.", view=None
        )
        self.stop()
