"""Backup cog: write a daily JSON snapshot of the configuration tables.

Reminders, triggers and whitelists already survive a rebuild because data/ is a
mounted volume — this guards against the other failure, where the database file
itself is lost or corrupted and there is nothing to fall back on.
"""

import datetime
import json
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from services.backup import TABLES, backup_dir_for, restore_config, summarise, write_backup

log = logging.getLogger(__name__)

# Fixed UTC+1 rather than ZoneInfo("Europe/Amsterdam") on purpose: this cog must
# not inherit the tzdata dependency that can stop cogs/reminders.py from loading.
# The cost is that the backup runs at 05:00 local during summer time, which for a
# nightly snapshot does not matter.
BACKUP_AT = datetime.time(hour=4, minute=0, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
KEEP_SNAPSHOTS = 14
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


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

    @backup.command(name="create", description="Maak nu direct een back-up. Gebeurt sowieso automatisch elke nacht om 04:00")
    async def create_cmd(self, interaction: discord.Interaction) -> None:
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

    @backup.command(name="download", description="Stuur de nieuwste back-up als bestand, alleen naar jou")
    async def download_cmd(self, interaction: discord.Interaction) -> None:
        dest = backup_dir_for(self.bot.settings.db_path)
        snapshots = sorted(dest.glob("config-backup-*.json"), reverse=True)
        if not snapshots:
            await interaction.response.send_message(
                "Er is nog geen back-up. Maak er een met `/backup create`.", ephemeral=True
            )
            return

        newest = snapshots[0]
        try:
            with newest.open("rb") as fh:
                await interaction.response.send_message(
                    f"🗄️ `{newest.name}` — {newest.stat().st_size / 1024:.1f} kB",
                    file=discord.File(fh, filename=newest.name),
                    ephemeral=True,
                )
        except OSError as exc:
            await interaction.response.send_message(
                f"🚫 Kon de back-up niet lezen: `{exc}`", ephemeral=True
            )

    @backup.command(name="restore", description="Zet een eerder gedownloade back-up terug. Overschrijft alles")
    @app_commands.describe(
        file="Het JSON-bestand uit /backup download",
        confirm="Zet op True. De huidige gegevens worden vervangen",
    )
    async def restore_cmd(
        self, interaction: discord.Interaction, file: discord.Attachment, confirm: bool
    ) -> None:
        if not confirm:
            await interaction.response.send_message(
                "🚫 Niets teruggezet. Zet `confirm` op **True** om door te gaan.", ephemeral=True
            )
            return

        if file.size > MAX_UPLOAD_BYTES:
            await interaction.response.send_message(
                f"🚫 Bestand is te groot ({file.size / 1024 / 1024:.1f} MB).", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            payload = json.loads((await file.read()).decode("utf-8"))
        except (discord.HTTPException, UnicodeDecodeError, json.JSONDecodeError) as exc:
            await interaction.followup.send(
                f"🚫 Kon het bestand niet lezen: `{exc}`\n"
                "Verwacht wordt het JSON-bestand uit `/backup download`.",
                ephemeral=True,
            )
            return

        # Guard against a well-formed JSON file that simply is not a snapshot —
        # restoring is destructive, so "looks like JSON" is not good enough.
        if not isinstance(payload, dict) or not isinstance(payload.get("tables"), dict):
            await interaction.followup.send(
                "🚫 Dit lijkt geen back-up van deze bot. Er wordt een bestand verwacht "
                "met een `tables`-onderdeel, zoals `/backup download` het geeft.",
                ephemeral=True,
            )
            return

        # Snapshot what is there now before overwriting it: the most likely
        # mistake is restoring the wrong file, and that has to be undoable too.
        try:
            safety = write_backup(self.bot.settings.db_path, keep=KEEP_SNAPSHOTS)
        except OSError as exc:
            await interaction.followup.send(
                f"🚫 Afgebroken: kon vooraf geen back-up maken (`{exc}`). Er is niets gewijzigd.",
                ephemeral=True,
            )
            return

        written = restore_config(self.bot.settings.db_path, payload, TABLES)
        log.info(
            "%s restored a backup in guild %s: %s",
            interaction.user, interaction.guild_id, written,
        )

        if not written:
            await interaction.followup.send(
                f"ℹ️ Er stond niets in dat bestand om terug te zetten.\n"
                f"🗄️ Je oude gegevens staan veilig in `{safety.name}`.",
                ephemeral=True,
            )
            return

        detail = "\n".join(f"• {name}: {n}" for name, n in sorted(written.items()))
        await interaction.followup.send(
            f"♻️ Teruggezet uit `{file.filename}` (gemaakt op "
            f"{payload.get('created_at', 'onbekend')}):\n{detail}\n\n"
            f"🗄️ Wat er stond is bewaard als `{safety.name}`.\n"
            "_Reminders en triggers zijn meteen actief; herstart is niet nodig._",
            ephemeral=True,
        )

    @backup.command(name="list", description="Toon welke back-ups er zijn, hoe recent en hoe groot")
    async def list_cmd(self, interaction: discord.Interaction) -> None:
        dest = backup_dir_for(self.bot.settings.db_path)
        snapshots = sorted(dest.glob("config-backup-*.json"), reverse=True)
        if not snapshots:
            await interaction.response.send_message(
                "Er zijn nog geen back-ups. Maak er een met `/backup create`.", ephemeral=True
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
