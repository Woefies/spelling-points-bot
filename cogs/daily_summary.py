"""Daily summary cog: post the day's mistake leaderboard at end of day.

Reads `issues_log` rather than `scores`, because `scores` only keeps running
totals and this needs "what happened today".
"""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

log = logging.getLogger(__name__)

TZ = ZoneInfo("Europe/Amsterdam")
CONFIG_CHANNEL = "daily_summary_channel"
CONFIG_TIME = "daily_summary_time"
DEFAULT_TIME = "16:30"
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def _utc_window_for_local_day(now: datetime) -> tuple[str, str]:
    """UTC bounds covering the Amsterdam day `now` falls in.

    issues_log.ts is UTC; the reporting day is local. Matching on the local date
    directly would misfile everything logged between midnight and 02:00 local.
    """
    start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    fmt = "%Y-%m-%d %H:%M:%S"
    return (
        start_local.astimezone(timezone.utc).strftime(fmt),
        end_local.astimezone(timezone.utc).strftime(fmt),
    )


class DailySummaryCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._last_posted: dict[int, str] = {}  # guild_id -> 'YYYY-MM-DD'
        self.check_summary.start()

    def cog_unload(self) -> None:
        self.check_summary.cancel()

    @tasks.loop(seconds=30)
    async def check_summary(self) -> None:
        now = datetime.now(TZ)
        if now.weekday() >= 5:  # weekend: nobody is logging hours anyway
            return

        today = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M")

        for guild_id, channel_id in self.bot.repo.all_config(CONFIG_CHANNEL):
            wanted = self.bot.repo.get_config(guild_id, CONFIG_TIME) or DEFAULT_TIME
            if current_time != wanted or self._last_posted.get(guild_id) == today:
                continue

            channel = self.bot.get_channel(int(channel_id))
            if channel is None:
                log.warning("Daily summary channel %s for guild %s not found", channel_id, guild_id)
                continue

            embed = self._build_embed(guild_id, now)
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                log.exception("Could not post daily summary in %s", channel_id)
                continue
            self._last_posted[guild_id] = today

    @check_summary.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()

    def _build_embed(self, guild_id: int, now: datetime) -> discord.Embed:
        start_utc, end_utc = _utc_window_for_local_day(now)
        rows = self.bot.repo.leaderboard_between(guild_id, start_utc, end_utc, 10)

        embed = discord.Embed(
            title=f"📋 Dagoverzicht — {now.strftime('%d-%m-%Y')}",
            color=discord.Color.orange(),
        )
        if not rows:
            embed.description = "Geen enkele fout vandaag. Verdacht. 🎉"
            return embed

        guild = self.bot.get_guild(guild_id)
        lines = []
        for rank, (user_id, count) in enumerate(rows, start=1):
            member = guild.get_member(user_id) if guild else None
            name = member.display_name if member else f"Gebruiker {user_id}"
            lines.append(f"{MEDALS.get(rank, f'{rank}.')} **{name}** — {count}")

        embed.description = "\n".join(lines)
        embed.set_footer(text=f"{sum(c for _, c in rows)} fouten vandaag")
        return embed

    # -------------------------------------------------------------- commands

    dagoverzicht = app_commands.Group(
        name="dagoverzicht",
        description="Dagelijkse ranglijst van de spelfouten van die dag, aan het eind van de werkdag",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @dagoverzicht.command(name="aan", description="Zet het dagoverzicht aan. Standaard elke werkdag om 16:30")
    @app_commands.describe(
        kanaal="In welk kanaal het overzicht elke werkdag geplaatst wordt",
        tijd=f"Tijd in HH:MM (standaard {DEFAULT_TIME}, alleen op werkdagen)",
    )
    async def enable_cmd(
        self,
        interaction: discord.Interaction,
        kanaal: discord.TextChannel,
        tijd: str | None = None,
    ) -> None:
        when = DEFAULT_TIME
        if tijd:
            try:
                when = datetime.strptime(tijd.strip(), "%H:%M").strftime("%H:%M")
            except ValueError:
                await interaction.response.send_message(
                    "🚫 Ongeldige tijd. Gebruik HH:MM, bijv. `16:30`.", ephemeral=True
                )
                return

        self.bot.repo.set_config(interaction.guild_id, CONFIG_CHANNEL, str(kanaal.id))
        self.bot.repo.set_config(interaction.guild_id, CONFIG_TIME, when)
        await interaction.response.send_message(
            f"✅ Dagoverzicht staat aan: elke werkdag om **{when}** in {kanaal.mention}.",
            ephemeral=True,
        )

    @dagoverzicht.command(name="uit", description="Zet het dagoverzicht uit. De punten blijven gewoon geteld worden")
    async def disable_cmd(self, interaction: discord.Interaction) -> None:
        self.bot.repo.set_config(interaction.guild_id, CONFIG_CHANNEL, None)
        self.bot.repo.set_config(interaction.guild_id, CONFIG_TIME, None)
        await interaction.response.send_message("🛑 Dagoverzicht staat uit.", ephemeral=True)

    @dagoverzicht.command(name="nu", description="Toon nu het overzicht van vandaag, zonder te wachten tot het eind van de dag")
    async def now_cmd(self, interaction: discord.Interaction) -> None:
        embed = self._build_embed(interaction.guild_id, datetime.now(TZ))
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DailySummaryCog(bot))
