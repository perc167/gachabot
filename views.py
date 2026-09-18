"""Reusable interactive views: page flipping and yes/no confirmation."""
import discord


class Paginator(discord.ui.View):
    """Flips through a prebuilt list of embeds. Only the invoker may click."""

    def __init__(self, embeds, owner_id: int, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.owner_id = owner_id
        self.index = 0
        self.message = None
        self._sync_labels()
        if len(embeds) == 1:
            self.clear_items()

    def _sync_labels(self):
        self.page_label.label = f"{self.index + 1}/{len(self.embeds)}"
        self.prev.disabled = self.index == 0
        self.next.disabled = self.index >= len(self.embeds) - 1

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
        await interaction.response.edit_message(
            embed=self.embeds[self.index], view=self
        )

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

    async def start(self, ctx):
        self.message = await ctx.send(embed=self.embeds[0], view=self)
        return self.message


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
