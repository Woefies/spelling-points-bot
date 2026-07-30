"""Insights cog: read the bot's own data from Discord instead of the host.

Everything here previously needed a shell on the machine running the container.
That is a single point of failure the moment the person with access is on
holiday, so the diagnostics live in Discord now.
"""

import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from services.backup import backup_dir_for

log = logging.getLogger(__name__)

KIND_LABELS = {
    "spelling": "spelling",
    "repeat": "dubbel woord",
    "grammar_nl": "grammatica",
}


class InsightsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="flagged", description="Toon welke woorden het vaakst als fout zijn aangemerkt"
    )
    @app_commands.describe(
        days="Over hoeveel dagen terug. Standaard 7",
        kind="Welke checker het aanmerkte. Leeg laten voor alles",
        limit="Hoeveel woorden tonen. Standaard 15",
    )
    @app_commands.choices(
        kind=[
            app_commands.Choice(name="spelling", value="spelling"),
            app_commands.Choice(name="dubbel woord", value="repeat"),
            app_commands.Choice(name="grammatica", value="grammar_nl"),
        ]
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def flagged(
        self,
        interaction: discord.Interaction,
        days: app_commands.Range[int, 1, 365] = 7,
        kind: app_commands.Choice[str] | None = None,
        limit: app_commands.Range[int, 1, 40] = 15,
    ) -> None:
        now = datetime.now(timezone.utc)
        fmt = "%Y-%m-%d %H:%M:%S"
        start = (now - timedelta(days=days)).strftime(fmt)
        end = now.strftime(fmt)

        rows = self.bot.repo.top_flagged(
            interaction.guild_id, start, end, kind.value if kind else None, limit
        )
        if not rows:
            await interaction.response.send_message(
                f"Geen fouten gevonden in de laatste **{days}** dagen.", ephemeral=True
            )
            return

        lines = []
        for word, row_kind, hits, users in rows:
            label = KIND_LABELS.get(row_kind, row_kind or "?")
            people = f", {users} personen" if users > 1 else ""
            lines.append(f"`{word}` — **{hits}×** ({label}{people})")

        scope = f" · alleen {kind.name}" if kind else ""
        embed = discord.Embed(
            title=f"🔤 Meest aangemerkt — laatste {days} dagen{scope}",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )
        embed.set_footer(
            text="Hoort een woord hier niet thuis? /whitelist add woord1, woord2"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="status", description="Toon wat er draait: onderdelen, woordenboek en opslag")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction) -> None:
        s = self.bot.settings

        # Which dictionary is live answers "did the Hunspell change actually
        # land?" without anyone reading the startup log.
        from services.checkers import REGISTRY

        checker = REGISTRY.get("spelling")
        backends = getattr(checker, "backends", {}) or {}
        dictionaries = (
            ", ".join(f"{lang}: `{name}`" for lang, name in sorted(backends.items()))
            if backends
            else "_nog niet geladen — er is nog geen bericht gecontroleerd_"
        )

        db = _size_of(s.db_path)
        snapshots = sorted(backup_dir_for(s.db_path).glob("config-backup-*.json"), reverse=True)
        last_backup = (
            f"`{snapshots[0].name}` ({len(snapshots)} bewaard)" if snapshots else "_nog geen_"
        )

        uptime = discord.utils.utcnow() - self.bot.started_at
        embed = discord.Embed(title="🩺 Status", color=discord.Color.green())
        embed.add_field(name="Versie", value=f"v{s.version}", inline=True)
        embed.add_field(name="Draait al", value=_duration(uptime), inline=True)
        embed.add_field(name="Database", value=db, inline=True)
        embed.add_field(name="Woordenboek", value=dictionaries, inline=False)
        embed.add_field(
            name=f"Onderdelen ({len(self.bot.cogs)})",
            value=", ".join(f"`{name}`" for name in sorted(self.bot.cogs)),
            inline=False,
        )
        embed.add_field(
            name="Geregistreerd",
            value=f"{self.bot.repo.total_issues(interaction.guild_id)} fouten in deze server",
            inline=True,
        )
        embed.add_field(name="Laatste back-up", value=last_backup, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


def _size_of(path: str) -> str:
    from pathlib import Path

    try:
        return f"{Path(path).stat().st_size / 1024:.0f} kB"
    except OSError:
        return "_onbekend_"


def _duration(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}u"
    if hours:
        return f"{hours}u {minutes}m"
    return f"{minutes}m"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(InsightsCog(bot))
