"""Punishment cog: time someone out after enough mistakes in one day.

Off by default, and `warn` mode exists because this is the one feature that can
actually stop a colleague from talking. Run it in warn mode first and look at
who *would* have been muted before switching it on.

Threshold, ladder and announcement texts are all per-guild settings rather than
constants: tuning this needs a Discord command, not a redeploy by whoever
happens to run the host.
"""

import logging
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from cogs.daily_summary import TZ, _utc_window_for_local_day
from services.punishment import (
    DEFAULT_LADDER,
    DEFAULT_MUTE_TEXT,
    DEFAULT_THRESHOLD,
    DEFAULT_WARN_TEXT,
    MODE_MUTE,
    MODE_OFF,
    MODE_WARN,
    PLACEHOLDERS,
    crossed,
    format_minutes,
    parse_ladder,
    render,
)

log = logging.getLogger(__name__)

CONFIG_MODE = "punish_mode"
CONFIG_THRESHOLD = "punish_threshold"
CONFIG_LADDER = "punish_ladder"
CONFIG_WARN_TEXT = "punish_warn_text"
CONFIG_MUTE_TEXT = "punish_mute_text"

RESET = "-"  # value that puts a custom text or ladder back to the built-in one
MODE_LABELS = {MODE_OFF: "uit", MODE_WARN: "waarschuwen", MODE_MUTE: "echt dempen"}
PREVIEW = {"count": 42, "minutes": "5 minuten"}


class PunishmentCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ---------------------------------------------------------------- config

    def _mode(self, guild_id: int) -> str:
        return self.bot.repo.get_config(guild_id, CONFIG_MODE) or MODE_OFF

    def _threshold(self, guild_id: int) -> int:
        raw = self.bot.repo.get_config(guild_id, CONFIG_THRESHOLD)
        try:
            return int(raw) if raw else DEFAULT_THRESHOLD
        except ValueError:
            return DEFAULT_THRESHOLD

    def _ladder(self, guild_id: int) -> tuple[int, ...]:
        raw = self.bot.repo.get_config(guild_id, CONFIG_LADDER)
        return (parse_ladder(raw) if raw else None) or DEFAULT_LADDER

    def _text(self, guild_id: int, key: str, fallback: str) -> str:
        return self.bot.repo.get_config(guild_id, key) or fallback

    # ----------------------------------------------------------------- event

    @commands.Cog.listener()
    async def on_mistakes_recorded(self, message: discord.Message, added: int) -> None:
        """Dispatched by the spelling cog once it has logged a message's issues."""
        guild_id = message.guild.id
        mode = self._mode(guild_id)
        if mode == MODE_OFF:
            return

        start, end = _utc_window_for_local_day(datetime.now(TZ))
        total = self.bot.repo.count_between(guild_id, message.author.id, start, end)
        minutes = crossed(total - added, total, self._threshold(guild_id), self._ladder(guild_id))
        if not minutes:
            return

        values = {
            "user": message.author.mention,
            "count": total,
            "minutes": format_minutes(minutes),
        }

        if mode == MODE_WARN:
            template = self._text(guild_id, CONFIG_WARN_TEXT, DEFAULT_WARN_TEXT)
            await self._say(message, render(template, DEFAULT_WARN_TEXT, **values))
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
                f"⚠️ {message.author.mention} zou **{format_minutes(minutes)}** gemute worden "
                f"({total} fouten), maar dat lukt niet. Mist de bot *Moderate Members*, "
                f"of staat zijn rol te laag?",
            )
            return
        except discord.HTTPException:
            log.exception("Timeout failed for %s", message.author)
            return

        template = self._text(guild_id, CONFIG_MUTE_TEXT, DEFAULT_MUTE_TEXT)
        await self._say(message, render(template, DEFAULT_MUTE_TEXT, **values))

    async def _say(self, message: discord.Message, text: str) -> None:
        try:
            # users=True on purpose: the point is that the person actually hears it.
            await message.channel.send(text, allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException:
            log.warning("Could not announce punishment in %s", message.channel.id)

    # -------------------------------------------------------------- commands

    punish = app_commands.Group(
        name="punish",
        description="Mute-regels bij te veel spelfouten op een dag",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @punish.command(name="mode", description="Zet straffen uit, op waarschuwen, of op echt dempen")
    @app_commands.describe(mode="Begin met waarschuwen om te zien wie er gemute zou worden")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="uit", value=MODE_OFF),
            app_commands.Choice(name="waarschuwen (dempt niemand)", value=MODE_WARN),
            app_commands.Choice(name="echt dempen", value=MODE_MUTE),
        ]
    )
    async def mode_cmd(
        self, interaction: discord.Interaction, mode: app_commands.Choice[str]
    ) -> None:
        self.bot.repo.set_config(interaction.guild_id, CONFIG_MODE, mode.value)

        extra = ""
        if mode.value == MODE_MUTE and not interaction.guild.me.guild_permissions.moderate_members:
            extra = "\n⚠️ De bot mist het recht **Moderate Members** — dempen gaat dan mislukken."
        await interaction.response.send_message(
            f"✅ Straffen staan op **{mode.name}**.{extra}", ephemeral=True
        )

    @punish.command(name="threshold", description="Na hoeveel fouten op een dag de eerste mute volgt")
    @app_commands.describe(amount="Aantal fouten per stap. Hoger is milder. Standaard 20")
    async def threshold_cmd(
        self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 1000]
    ) -> None:
        self.bot.repo.set_config(interaction.guild_id, CONFIG_THRESHOLD, str(amount))
        await interaction.response.send_message(
            f"✅ Drempel staat op **{amount}** fouten per dag.\n"
            f"{self._ladder_text(interaction.guild_id)}",
            ephemeral=True,
        )

    @punish.command(name="ladder", description="Stel zelf in hoe lang elke mute duurt, in minuten")
    @app_commands.describe(
        minutes="Minuten per stap met kommas: 1, 2, 5, 10, 20, 30. Typ - voor de standaard"
    )
    async def ladder_cmd(self, interaction: discord.Interaction, minutes: str) -> None:
        if minutes.strip() == RESET:
            self.bot.repo.set_config(interaction.guild_id, CONFIG_LADDER, None)
            await interaction.response.send_message(
                f"✅ Ladder terug op standaard.\n{self._ladder_text(interaction.guild_id)}",
                ephemeral=True,
            )
            return

        parsed = parse_ladder(minutes)
        if parsed is None:
            await interaction.response.send_message(
                "🚫 Ongeldig. Geef hele minuten van 1 t/m 1440, gescheiden door komma's, "
                "bijvoorbeeld `1, 2, 5, 10, 20, 30`.",
                ephemeral=True,
            )
            return

        self.bot.repo.set_config(interaction.guild_id, CONFIG_LADDER, ",".join(map(str, parsed)))
        await interaction.response.send_message(
            f"✅ Ladder aangepast.\n{self._ladder_text(interaction.guild_id)}", ephemeral=True
        )

    @punish.command(name="message", description="Schrijf zelf wat de bot zegt bij een waarschuwing of mute")
    @app_commands.describe(
        type="Welke melding je wilt aanpassen",
        text="Gebruik {user}, {count} en {minutes}. Typ - om de standaardtekst terug te zetten",
    )
    @app_commands.choices(
        type=[
            app_commands.Choice(name="waarschuwing", value=CONFIG_WARN_TEXT),
            app_commands.Choice(name="mute", value=CONFIG_MUTE_TEXT),
        ]
    )
    async def message_cmd(
        self, interaction: discord.Interaction, type: app_commands.Choice[str], text: str
    ) -> None:
        default = DEFAULT_WARN_TEXT if type.value == CONFIG_WARN_TEXT else DEFAULT_MUTE_TEXT
        who = interaction.user.mention

        if text.strip() == RESET:
            self.bot.repo.set_config(interaction.guild_id, type.value, None)
            await interaction.response.send_message(
                f"✅ Standaardtekst hersteld:\n>>> {default.format(user=who, **PREVIEW)}",
                ephemeral=True,
            )
            return

        # render() falls back to the default on a malformed template, so an
        # identical result means the template was rejected. Better to say so now
        # than to discover it the first time someone crosses the threshold.
        preview = render(text, default, user=who, **PREVIEW)
        if preview == default.format(user=who, **PREVIEW):
            await interaction.response.send_message(
                "🚫 Die tekst kon niet ingevuld worden. Gebruik alleen "
                f"{', '.join(f'`{p}`' for p in PLACEHOLDERS)} en let op je accolades.",
                ephemeral=True,
            )
            return

        self.bot.repo.set_config(interaction.guild_id, type.value, text)
        await interaction.response.send_message(
            f"✅ Tekst opgeslagen. Zo ziet hij eruit:\n>>> {preview}", ephemeral=True
        )

    @punish.command(name="status", description="Toon de huidige instellingen en de hele mute-ladder")
    async def status_cmd(self, interaction: discord.Interaction) -> None:
        gid = interaction.guild_id
        custom = [
            name
            for name, key in (("waarschuwing", CONFIG_WARN_TEXT), ("mute", CONFIG_MUTE_TEXT))
            if self.bot.repo.get_config(gid, key)
        ]
        await interaction.response.send_message(
            f"⚖️ Straffen: **{MODE_LABELS[self._mode(gid)]}** · "
            f"drempel **{self._threshold(gid)}** fouten per dag\n"
            f"{self._ladder_text(gid)}\n"
            f"Eigen teksten: {', '.join(custom) if custom else 'geen, beide standaard'}\n\n"
            f"**Waarschuwing:**\n>>> {self._text(gid, CONFIG_WARN_TEXT, DEFAULT_WARN_TEXT)}\n"
            f"**Mute:**\n>>> {self._text(gid, CONFIG_MUTE_TEXT, DEFAULT_MUTE_TEXT)}",
            ephemeral=True,
        )

    def _ladder_text(self, guild_id: int) -> str:
        threshold = self._threshold(guild_id)
        ladder = self._ladder(guild_id)
        rungs = [f"{threshold * (i + 1)} → {m} min" for i, m in enumerate(ladder)]
        return "> " + " · ".join(rungs) + f" · daarna blijft het {ladder[-1]} min"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PunishmentCog(bot))
