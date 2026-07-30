"""Settings cog: change how strict the spelling check is, from Discord.

These four used to live only in .env, which put the bot's emergency brake behind
shell access to the host. A server overrides what it needs; anything left alone
keeps the .env value.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.guild_settings import FIELDS, LABELS, describe, resolve, store

log = logging.getLogger(__name__)


class SettingsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _current(self, guild_id: int) -> dict:
        return resolve(self.bot.repo.config_for(guild_id), self.bot.settings)

    async def _save(self, interaction: discord.Interaction, key: str, value) -> None:
        self.bot.repo.set_config(interaction.guild_id, key, store(value))
        log.info("%s set %s=%r in guild %s", interaction.user, key, value, interaction.guild_id)
        await interaction.response.send_message(
            f"✅ **{LABELS[key]}** staat nu op **{describe(key, value)}**.", ephemeral=True
        )

    settings = app_commands.Group(
        name="settings",
        description="Instellen hoe streng de spellingcheck is",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @settings.command(name="show", description="Toon de huidige instellingen van de spellingcheck")
    async def show_cmd(self, interaction: discord.Interaction) -> None:
        stored = self.bot.repo.config_for(interaction.guild_id)
        current = self._current(interaction.guild_id)
        lines = [
            f"• **{LABELS[key]}**: {describe(key, current[key])}"
            + ("" if key in stored else " _(standaard)_")
            for key in FIELDS
        ]
        await interaction.response.send_message(
            "⚙️ **Spellingcheck**\n" + "\n".join(lines)
            + "\n\n_Zet punten op 0 of antwoorden uit om de bot stil te zetten "
            "zonder hem te stoppen._",
            ephemeral=True,
        )

    @settings.command(name="points", description="Hoeveel strafpunten een fout kost. 0 = niets tellen")
    @app_commands.describe(amount="Punten per fout. Zet op 0 om het puntensysteem stil te zetten")
    async def points_cmd(
        self, interaction: discord.Interaction, amount: app_commands.Range[int, 0, 100]
    ) -> None:
        await self._save(interaction, "points_per_mistake", amount)

    @settings.command(name="reply", description="Of de bot antwoordt bij een fout, of stil punten telt")
    @app_commands.describe(enabled="Uit betekent: nog wel een kruisje en punten, geen bericht")
    async def reply_cmd(self, interaction: discord.Interaction, enabled: bool) -> None:
        await self._save(interaction, "reply_on_mistake", enabled)

    @settings.command(name="minwords", description="Vanaf hoeveel woorden een bericht gecontroleerd wordt")
    @app_commands.describe(amount="Hoger betekent dat korte berichtjes met rust gelaten worden")
    async def minwords_cmd(
        self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 50]
    ) -> None:
        await self._save(interaction, "min_words_for_detect", amount)

    @settings.command(name="capitals", description="Woorden met een hoofdletter overslaan (namen)")
    @app_commands.describe(enabled="Aan laten voorkomt dat namen als fout gerekend worden")
    async def capitals_cmd(self, interaction: discord.Interaction, enabled: bool) -> None:
        await self._save(interaction, "skip_capitalized", enabled)

    @settings.command(name="reset", description="Alles terug naar de standaardwaarden van de server")
    async def reset_cmd(self, interaction: discord.Interaction) -> None:
        removed = [k for k in FIELDS if self.bot.repo.get_config(interaction.guild_id, k)]
        for key in removed:
            self.bot.repo.set_config(interaction.guild_id, key, None)
        if not removed:
            await interaction.response.send_message(
                "ℹ️ Er stonden geen eigen instellingen — alles was al standaard.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"🧹 {len(removed)} instelling(en) teruggezet op standaard.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))
