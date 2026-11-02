"""cogs/language.py - the language picker, /language, and the join prompt."""
import discord
from discord import app_commands
from discord.ext import commands

import i18n

PICKER = dict(list(i18n.LANGUAGES.items())[:i18n.PICKER_SIZE])

PROMPT_LINES = [
    "**Select your language**", "Selecciona tu idioma", "Selecione seu idioma",
    "Choisissez votre langue", "Wähle deine Sprache", "Seleziona la tua lingua",
    "Piliin ang iyong wika", "Pilih bahasa Anda", "Chọn ngôn ngữ của bạn",
    "เลือกภาษาของคุณ", "言語を選択してください", "언어를 선택하세요", "选择你的语言",
    "Выберите ваш язык", "Dilinizi seçin", "اختر لغتك", "अपनी भाषा चुनें",
]


async def apply_language(interaction: discord.Interaction, code: str) -> None:
    i18n.set_user_lang(interaction.user.id, code)

    # Someone who can manage the server also sets its default, so everyone
    # who has not chosen for themselves follows.
    for_server = False
    if interaction.guild and interaction.user.guild_permissions.manage_guild:
        i18n.set_guild_lang(interaction.guild.id, code)
        for_server = True

    msg = i18n.t(code, "language.set", language=i18n.LANGUAGES[code])
    if for_server:
        msg += "\n" + i18n.t(code, "language.set_server")
    await interaction.response.send_message(msg, ephemeral=True)


class LanguageSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=name, value=code)
                   for code, name in PICKER.items()]
        options.append(discord.SelectOption(label="More languages…",
                                            value="more", emoji="🌐"))
        super().__init__(
            custom_id="paper:language_select",  # fixed, so it survives redeploys
            placeholder="Language / Idioma / Wika…",
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        if value == "more":
            await interaction.response.send_message(
                "Use `/language` and start typing your language to search.",
                ephemeral=True)
            return
        await apply_language(interaction, value)


class LanguageView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(LanguageSelect())


def prompt_embed() -> discord.Embed:
    return discord.Embed(description="\n".join(PROMPT_LINES),
                         color=discord.Color.blurple())


async def language_autocomplete(interaction: discord.Interaction, current: str):
    current = current.lower().strip()
    return [
        app_commands.Choice(name=name, value=code)
        for code, name in i18n.LANGUAGES.items()
        if current in name.lower() or current in code
    ][:25]


class Language(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(LanguageView())

    @app_commands.command(name="language", description="Choose your language")
    @app_commands.describe(language="Start typing to search")
    @app_commands.autocomplete(language=language_autocomplete)
    async def language(self, interaction: discord.Interaction, language: str):
        if language not in i18n.LANGUAGES:
            await interaction.response.send_message(
                "Pick a language from the list that appears as you type.",
                ephemeral=True)
            return
        await apply_language(interaction, language)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        channel = guild.system_channel
        if channel is None or not channel.permissions_for(guild.me).send_messages:
            channel = next((c for c in guild.text_channels
                            if c.permissions_for(guild.me).send_messages), None)
        if channel:
            await channel.send(embed=prompt_embed(), view=LanguageView())


async def setup(bot: commands.Bot):
    i18n.init(bot.db)   # <- change if your Database object is named differently
    await bot.add_cog(Language(bot))
