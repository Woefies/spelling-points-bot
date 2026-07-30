"""Reset cog: wipe a category of configuration for this server.

Every reset takes a backup snapshot first, so a misclick is recoverable with
scripts/import_config.py rather than gone for good.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.backup import write_backup

log = logging.getLogger(__name__)

# Label -> (table key for repo.clear, what to tell the user they are losing)
RESETTABLE: dict[str, tuple[tuple[str, ...], str]] = {
    "reminders": (("reminders",), "alle herinneringen"),
    "triggers": (("triggers",), "alle triggers"),
    "whitelist": (("whitelist",), "alle goedgekeurde woorden"),
    "punten": (("scores",), "alle puntenstanden"),
    "instellingen": (("guild_config",), "het dagoverzicht-kanaal en -tijd"),
    "alles": (
        ("reminders", "triggers", "whitelist", "scores", "guild_config"),
        "ALLES: herinneringen, triggers, whitelist, punten en instellingen",
    ),
}


class ResetCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="reset", description="Wis een onderdeel van de instellingen van deze server"
    )
    @app_commands.describe(
        onderdeel="Wat je wilt wissen. Er wordt eerst automatisch een back-up gemaakt",
        bevestig="Zet op True. Dit verwijdert gegevens en kan niet ongedaan gemaakt worden",
    )
    @app_commands.choices(
        onderdeel=[
            app_commands.Choice(name="herinneringen", value="reminders"),
            app_commands.Choice(name="triggers", value="triggers"),
            app_commands.Choice(name="whitelist", value="whitelist"),
            app_commands.Choice(name="puntenstanden", value="punten"),
            app_commands.Choice(name="instellingen (dagoverzicht)", value="instellingen"),
            app_commands.Choice(name="ALLES", value="alles"),
        ]
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def reset(
        self,
        interaction: discord.Interaction,
        onderdeel: app_commands.Choice[str],
        bevestig: bool,
    ) -> None:
        tables, human = RESETTABLE[onderdeel.value]

        if not bevestig:
            await interaction.response.send_message(
                f"🚫 Niets gewist. Zet `bevestig` op **True** om {human} echt te verwijderen.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Backup before deleting, never after — if the wipe half-succeeds the
        # snapshot is the only way back.
        backup_note = ""
        try:
            path = write_backup(self.bot.settings.db_path)
            backup_note = f"\n🗄️ Back-up vooraf: `{path.name}`"
        except OSError as exc:
            log.warning("Backup before reset failed: %s", exc)
            await interaction.followup.send(
                f"🚫 Afgebroken: de back-up vooraf mislukte (`{exc}`). Er is niets gewist.",
                ephemeral=True,
            )
            return

        removed = {t: self.bot.repo.clear(interaction.guild_id, t) for t in tables}
        total = sum(removed.values())
        log.info("Reset '%s' in guild %s removed %d row(s)", onderdeel.value, interaction.guild_id, total)

        if total == 0:
            await interaction.followup.send(
                f"ℹ️ Er was niets om te wissen bij **{onderdeel.name}**.{backup_note}",
                ephemeral=True,
            )
            return

        detail = "\n".join(f"• {name}: {n}" for name, n in removed.items() if n)
        await interaction.followup.send(
            f"🧹 **{onderdeel.name}** gewist — {total} regel(s) verwijderd:\n{detail}"
            f"{backup_note}\n\n"
            "_Toch te snel geweest? De back-up terugzetten kan met `scripts/import_config.py`._",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ResetCog(bot))
