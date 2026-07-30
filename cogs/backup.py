"""Backup cog: write a daily JSON snapshot of the configuration tables.

Reminders, triggers and whitelists already survive a rebuild because data/ is a
mounted volume — this guards against the other failure, where the database file
itself is lost or corrupted and there is nothing to fall back on.
"""

import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from services.backup import backup_dir_for, summarise, write_backup

log = logging.getLogger(__name__)

# Fixed UTC+1 rather than ZoneInfo("Europe/Amsterdam") on purpose: this cog must
# not inherit the tzdata dependency that can stop cogs/reminders.py from loading.
# The cost is that the backup runs at 05:00 local during summer time, which for a
# nightly snapshot does not matter.
BACKUP_AT = datetime.time(hour=4, minute=0, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
KEEP_SNAPSHOTS = 14


class BackupCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.daily_backup.start()

    def cog_unload(self) -> None:
        self.daily_backup.cancel()

    @tasks.loop(time=BACKUP_AT)
    async def daily_backup(self) -> None:
        self._run_backup()

    @daily_backup.before_loop
    async def before_backup(self) -> None:
        await self.bot.wait_until_ready()

    def _run_backup(self):
        """Returns (path, summary) or raises."""
        path = write_backup(self.bot.settings.db_path, keep=KEEP_SNAPSHOTS)
        from services.backup import export_config

        summary = summarise(export_config(self.bot.settings.db_path))
        log.info("Config backup written to %s (%s)", path, summary)
        return path, summary

    # -------------------------------------------------------------- commands

    backup = app_commands.Group(
        name="backup",
        description="Back-ups van reminders, triggers, whitelist en puntenstanden",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @backup.command(name="now", description="Maak nu direct een back-up. Gebeurt sowieso automatisch elke nacht om 04:00")
    async def now_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            path, summary = self._run_backup()
        except OSError as exc:
            # Most likely cause on a NAS: the mounted data/ volume is read-only
            # for the container. Worth saying out loud rather than failing mutely.
            await interaction.followup.send(
                f"🚫 Back-up mislukt: `{exc}`\nKan de bot wel schrijven in `data/`?",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"✅ Back-up gemaakt: `{path.name}`\n{summary}", ephemeral=True
        )

    @backup.command(name="list", description="Toon welke back-ups er zijn, hoe recent en hoe groot")
    async def list_cmd(self, interaction: discord.Interaction) -> None:
        dest = backup_dir_for(self.bot.settings.db_path)
        snapshots = sorted(dest.glob("config-backup-*.json"), reverse=True)
        if not snapshots:
            await interaction.response.send_message(
                "Er zijn nog geen back-ups. Maak er een met `/backup now`.", ephemeral=True
            )
            return

        lines = [
            f"• `{p.name}` — {p.stat().st_size / 1024:.1f} kB" for p in snapshots[:KEEP_SNAPSHOTS]
        ]
        await interaction.response.send_message(
            f"🗄️ **{len(snapshots)} back-up(s)** in `{dest}`:\n" + "\n".join(lines),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BackupCog(bot))
