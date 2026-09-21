"""Reusable interactive views: page flipping and yes/no confirmation."""
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


class CharacterPicker(discord.ui.View):
    """A dropdown of somebody's harem, so a trade needs no typing.

    Discord allows 25 options in a select, and a harem can be longer, so the
    list pages. Only `owner_id` may touch it; everyone else gets told whose
    turn it is. When it finishes, `chosen` holds the picked row or None.
    """

    PER_PAGE = 25

    def __init__(self, rows, owner_id: int, placeholder: str, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.rows = rows
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

    def _build(self):
        self.clear_items()
        start = self.page * self.PER_PAGE
        window = self.rows[start : start + self.PER_PAGE]

        select = discord.ui.Select(
            placeholder=f"{self.placeholder} ({len(self.rows)} to choose from)",
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

        if self.pages > 1:
            previous = discord.ui.Button(label="◀", row=1)
            previous.disabled = self.page == 0
            previous.callback = self._on_prev
            self.add_item(previous)

            label = discord.ui.Button(
                label=f"{self.page + 1}/{self.pages}", row=1, disabled=True
            )
            self.add_item(label)

            nxt = discord.ui.Button(label="▶", row=1)
            nxt.disabled = self.page >= self.pages - 1
            nxt.callback = self._on_next
            self.add_item(nxt)

        cancel = discord.ui.Button(
            label="Cancel", style=discord.ButtonStyle.danger, row=1
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
        self.chosen = next((r for r in self.rows if r["id"] == character_id), None)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

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
