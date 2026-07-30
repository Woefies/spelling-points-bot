"""Punishment cog: time someone out after enough mistakes in one day.

Off by default, and `warn` mode exists because this is the one feature that can
actually stop a colleague from talking. Run it in warn mode first and look at
who *would* have been muted before switching it on.
"""

import logging
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from cogs.daily_summary import TZ, _utc_window_for_local_day
from services.punishment import (
    DEFAULT_THRESHOLD,
    LADDER_MINUTES,
    MODE_MUTE,
    MODE_OFF,
    MODE_WARN,
    crossed,
)

log = logging.getLogger(__name__)

CONFIG_MODE = "punish_mode"
CONFIG_THRESHOLD = "punish_threshold"


class PunishmentCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _settings_for(self, guild_id: int) -> tuple[str, int]:
        mode = self.bot.repo.get_config(guild_id, CONFIG_MODE) or MODE_OFF
        raw = self.bot.repo.get_config(guild_id, CONFIG_THRESHOLD)
        try:
            threshold = int(raw) if raw else DEFAULT_THRESHOLD
        except ValueError:
            threshold = DEFAULT_THRESHOLD
        return mode, threshold

    @commands.Cog.listener()
    async def on_mistakes_recorded(self, message: discord.Message, added: int) -> None:
        """Dispatched by the spelling cog once it has logged a message's issues."""
        guild_id = message.guild.id
        mode, threshold = self._settings_for(guild_id)
        if mode == MODE_OFF:
            return

        start, end = _utc_window_for_local_day(datetime.now(TZ))
        total = self.bot.repo.count_between(guild_id, message.author.id, start, end)
        minutes = crossed(total - added, total, threshold)
        if not minutes:
            return

        if mode == MODE_WARN:
            await self._say(
                message,
                f"⚠️ {message.author.mention} zit op **{total}** fouten vandaag. "
                f"Dit zou een mute van **{minutes} minuten** zijn geweest.\n"
                f"_De bot staat in waarschuwingsmodus en dempt nog niemand._",
            )
            return

        try:
            await message.author.timeout(
                timedelta(minutes=minutes), reason=f"{total} spelfouten vandaag"
            )
        except discord.Forbidden:
            # Either the bot lacks Moderate Members, its role sits below the
            # target's, or the target is an admin — Discord refuses all three.
            log.warning("Could not time out %s in guild %s", message.author, guild_id)
            await self._say(
                message,
                f"⚠️ {message.author.mention} zou **{minutes} minuten** gemute worden "
                f"({total} fouten), maar dat lukt niet. Mist de bot *Moderate Members*, "
                f"of staat zijn rol te laag?",
            )
            return
        except discord.HTTPException:
            log.exception("Timeout failed for %s", message.author)
            return

        await self._say(
            message,
            f"🔇 {message.author.mention} is **{minutes} minuten** gemute — "
            f"**{total}** fouten vandaag.",
        )

    async def _say(self, message: discord.Message, text: str) -> None:
        try:
            await message.channel.send(text, allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException:
            log.warning("Could not announce punishment in %s", message.channel.id)

    # -------------------------------------------------------------- commands

    straf = app_commands.Group(
        name="straf",
        description="Mute-regels bij te veel spelfouten op een dag",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @straf.command(name="modus", description="Zet straffen uit, op waarschuwen, of op echt dempen")
    @app_commands.describe(modus="Begin met waarschuwen om te zien wie er gemute zou worden")
    @app_commands.choices(
        modus=[
            app_commands.Choice(name="uit", value=MODE_OFF),
            app_commands.Choice(name="waarschuwen (dempt niemand)", value=MODE_WARN),
            app_commands.Choice(name="echt dempen", value=MODE_MUTE),
        ]
    )
    async def mode_cmd(
        self, interaction: discord.Interaction, modus: app_commands.Choice[str]
    ) -> None:
        self.bot.repo.set_config(interaction.guild_id, CONFIG_MODE, modus.value)
        _, threshold = self._settings_for(interaction.guild_id)

        extra = ""
        if modus.value == MODE_MUTE:
            me = interaction.guild.me
            if not me.guild_permissions.moderate_members:
                extra = "\n⚠️ De bot mist het recht **Moderate Members** — dempen gaat dan mislukken."
        await interaction.response.send_message(
            f"✅ Straffen staan op **{modus.name}** (drempel: {threshold} fouten per dag).{extra}",
            ephemeral=True,
        )

    @straf.command(name="drempel", description="Na hoeveel fouten op een dag de eerste mute volgt")
    @app_commands.describe(aantal="Aantal fouten per stap. Hoger is milder. Standaard 20")
    async def threshold_cmd(
        self, interaction: discord.Interaction, aantal: app_commands.Range[int, 1, 1000]
    ) -> None:
        self.bot.repo.set_config(interaction.guild_id, CONFIG_THRESHOLD, str(aantal))
        await interaction.response.send_message(
            f"✅ Drempel staat op **{aantal}** fouten per dag.\n{_ladder_text(aantal)}",
            ephemeral=True,
        )

    @straf.command(name="status", description="Toon de huidige instellingen en de hele mute-ladder")
    async def status_cmd(self, interaction: discord.Interaction) -> None:
        mode, threshold = self._settings_for(interaction.guild_id)
        labels = {MODE_OFF: "uit", MODE_WARN: "waarschuwen", MODE_MUTE: "echt dempen"}
        await interaction.response.send_message(
            f"⚖️ Straffen: **{labels[mode]}** · drempel **{threshold}** fouten per dag\n"
            f"{_ladder_text(threshold)}",
            ephemeral=True,
        )


def _ladder_text(threshold: int) -> str:
    rungs = [f"{threshold * (i + 1)} fouten → {m} min" for i, m in enumerate(LADDER_MINUTES)]
    return "> " + " · ".join(rungs) + " · daarna blijft het 30 min"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PunishmentCog(bot))
