"""Test-mode cog: point the bot at a sandbox channel.

Nothing here changes what the bot does — it changes where the consequences land.
See services/testmode.py for the three states and why they fail open.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.testmode import (
    CONFIG_CHANNEL,
    CONFIG_ISOLATE,
    isolated,
    test_channel_id,
)

log = logging.getLogger(__name__)


class TestModeCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    test = app_commands.Group(
        name="test",
        description="Wijs een testkanaal aan waar de bot reageert zonder iets op te slaan",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @test.command(name="channel", description="Kies het kanaal waar je veilig kunt testen")
    @app_commands.describe(channel="Hier reageert de bot wel, maar telt niets mee")
    async def channel_cmd(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        self.bot.repo.set_config(interaction.guild_id, CONFIG_CHANNEL, str(channel.id))
        await interaction.response.send_message(
            f"🧪 Testkanaal staat op {channel.mention}.\n"
            "Daar reageert de bot precies zoals altijd — kruisje, antwoord, triggers, AI — "
            "maar er worden **geen punten geteld, geen triggers geregistreerd en niemand "
            "gedempt**. De dagsamenvatting merkt er niets van.\n"
            "_Wil je dat de bot tijdens het testen even nergens anders reageert: "
            "`/test isolate enabled:True`._",
            ephemeral=True,
        )

    @test.command(name="isolate", description="Laat de bot tijdens het testen alleen in het testkanaal reageren")
    @app_commands.describe(enabled="Aan betekent dat de bot in alle andere kanalen stil blijft")
    async def isolate_cmd(self, interaction: discord.Interaction, enabled: bool) -> None:
        config = self.bot.repo.config_for(interaction.guild_id)
        if enabled and test_channel_id(config) is None:
            await interaction.response.send_message(
                "🚫 Stel eerst een testkanaal in met `/test channel`. Zonder kanaal zou de "
                "bot overal stil vallen en was er geen plek meer over om hem weer aan te zetten.",
                ephemeral=True,
            )
            return

        self.bot.repo.set_config(
            interaction.guild_id, CONFIG_ISOLATE, "1" if enabled else None
        )
        if enabled:
            channel = f"<#{test_channel_id(config)}>"
            await interaction.response.send_message(
                f"🔇 De bot reageert nu **alleen** nog in {channel}.\n"
                "In alle andere kanalen worden er geen fouten geteld en reageert hij "
                "nergens op. Reminders blijven wel gewoon versturen.\n"
                "_Vergeet dit niet uit te zetten: `/test isolate enabled:False`._",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "🔊 De bot reageert weer in alle kanalen. Het testkanaal blijft staan.",
                ephemeral=True,
            )

    @test.command(name="off", description="Zet de testmodus helemaal uit en wis het testkanaal")
    async def off_cmd(self, interaction: discord.Interaction) -> None:
        # Both keys, always. Leaving isolate behind after clearing the channel is
        # how you end up with a setting nobody can see and nobody can explain.
        self.bot.repo.set_config(interaction.guild_id, CONFIG_CHANNEL, None)
        self.bot.repo.set_config(interaction.guild_id, CONFIG_ISOLATE, None)
        await interaction.response.send_message(
            "✅ Testmodus uit. De bot telt weer overal mee.", ephemeral=True
        )

    @test.command(name="status", description="Toon of er een testkanaal is en of de bot geisoleerd staat")
    async def status_cmd(self, interaction: discord.Interaction) -> None:
        config = self.bot.repo.config_for(interaction.guild_id)
        channel_id = test_channel_id(config)
        if channel_id is None:
            await interaction.response.send_message(
                "🧪 Geen testkanaal ingesteld — de bot telt overal gewoon mee.\n"
                "_Instellen met `/test channel`._",
                ephemeral=True,
            )
            return

        if isolated(config):
            where = f"**alleen** in <#{channel_id}>, en nergens anders"
        else:
            where = f"overal, en in <#{channel_id}> zonder gevolgen"
        await interaction.response.send_message(
            f"🧪 Testkanaal: <#{channel_id}>\nDe bot reageert {where}.\n\n"
            "In het testkanaal worden geen punten geteld, geen triggers geregistreerd "
            "en wordt er niemand gedempt.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TestModeCog(bot))
