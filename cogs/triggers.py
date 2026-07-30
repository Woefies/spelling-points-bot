"""Triggers cog: react to keywords in messages with a reply, emoji, or both.

Separate from the spelling checkers on purpose — a trigger is a social nudge, not
a mistake, so it awards no points.

No trigger text lives in this file: every trigger is created at runtime with
/trigger add and stored in the database, so changing one never needs a code
change or a redeploy.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.variants import compile_phrases, pick_variant

log = logging.getLogger(__name__)

CLEAR = "-"  # sentinel in /trigger edit meaning "empty this field"

class TriggersCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return

        replied = False
        for trig in self.bot.repo.list_triggers(message.guild.id):
            if not compile_phrases(trig.pattern).search(message.content):
                continue

            for emoji in _reaction_list(trig.reactions):
                try:
                    await message.add_reaction(emoji)
                except discord.HTTPException:
                    log.warning("Could not react with %r on trigger %d", emoji, trig.id)

            # At most one reply per message, however many triggers matched —
            # otherwise a single sentence can make the bot spam the channel.
            if trig.response and not replied:
                replied = True
                try:
                    await message.reply(
                        pick_variant(trig.response),
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException:
                    log.warning("Could not reply for trigger %d", trig.id)

    # --------------------------------------------------------- autocomplete

    async def _trigger_choices(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[int]]:
        term = current.lower()
        choices = []
        for trig in self.bot.repo.list_triggers(interaction.guild_id):
            what = trig.reactions or (trig.response or "").split("|")[0].strip()
            label = f"#{trig.id} · {trig.pattern} → {what}"
            if len(label) > 100:
                label = label[:97] + "..."
            if term and term not in label.lower():
                continue
            choices.append(app_commands.Choice(name=label, value=trig.id))
        return choices[:25]

    # -------------------------------------------------------------- commands

    trigger = app_commands.Group(
        name="trigger",
        description="Beheer woorden waar de bot automatisch op reageert met tekst of emoji",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @trigger.command(name="add", description="Laat de bot op een woord reageren met een tekst, emoji of allebei")
    @app_commands.describe(
        woorden="Waar de bot op let. Meerdere schrijfwijzen met |: thuiswerken|thuis werken",
        antwoord="Wat de bot terugzegt. Varianten met | zodat hij afwisselt. Leeg = niets zeggen",
        reacties="Emoji onder het bericht, gescheiden door kommas. Bijvoorbeeld: 👎,❌",
    )
    async def add_cmd(
        self,
        interaction: discord.Interaction,
        woorden: str,
        antwoord: str | None = None,
        reacties: str | None = None,
    ) -> None:
        if not antwoord and not reacties:
            await interaction.response.send_message(
                "🚫 Vul minstens `antwoord` of `reacties` in, anders doet de trigger niets.",
                ephemeral=True,
            )
            return

        if self.bot.repo.trigger_exists(interaction.guild_id, woorden):
            await interaction.response.send_message(
                f"🚫 Er bestaat al een trigger op `{woorden}`. Bekijk ze met `/trigger list`.",
                ephemeral=True,
            )
            return

        trigger_id = self.bot.repo.add_trigger(interaction.guild_id, woorden, antwoord, reacties)
        await interaction.response.send_message(
            f"✅ Trigger **#{trigger_id}** aangemaakt op: `{woorden}`",
            ephemeral=True,
        )

    @trigger.command(name="edit", description="Wijzig de woorden, het antwoord of de reacties van een trigger")
    @app_commands.autocomplete(id=_trigger_choices)
    @app_commands.describe(
        id="Kies de trigger die je wilt aanpassen",
        woorden="Nieuwe schrijfwijzen, gescheiden met |. Leeg laten = ongewijzigd",
        antwoord="Nieuw antwoord, varianten met |. Typ een - om het antwoord te wissen",
        reacties="Nieuwe emoji, gescheiden door kommas. Typ een - om ze te wissen",
    )
    async def edit_cmd(
        self,
        interaction: discord.Interaction,
        id: int,
        woorden: str | None = None,
        antwoord: str | None = None,
        reacties: str | None = None,
    ) -> None:
        existing = self.bot.repo.get_trigger(interaction.guild_id, id)
        if existing is None:
            await interaction.response.send_message(
                f"🚫 Geen trigger met ID **{id}**. Bekijk ze met `/trigger list`.", ephemeral=True
            )
            return

        # A lone "-" means "make this empty", which is different from leaving the
        # field out. Without it there would be no way to drop a reply or the emoji.
        changes: dict = {}
        if woorden is not None:
            changes["pattern"] = woorden
        if antwoord is not None:
            changes["response"] = None if antwoord.strip() == CLEAR else antwoord
        if reacties is not None:
            changes["reactions"] = None if reacties.strip() == CLEAR else reacties

        if not changes:
            await interaction.response.send_message(
                "🚫 Vul minstens één veld in dat je wilt wijzigen.", ephemeral=True
            )
            return

        if not changes.get("pattern", existing.pattern).strip():
            await interaction.response.send_message(
                "🚫 `woorden` mag niet leeg zijn — dan weet de bot nergens op te letten.",
                ephemeral=True,
            )
            return

        response = changes.get("response", existing.response)
        reactions = changes.get("reactions", existing.reactions)
        if not response and not reactions:
            await interaction.response.send_message(
                "🚫 Dan blijft er niets over: houd een `antwoord` of `reacties` over, "
                "anders doet de trigger niets. Verwijderen kan met `/trigger remove`.",
                ephemeral=True,
            )
            return

        self.bot.repo.update_trigger(interaction.guild_id, id, changes)
        updated = self.bot.repo.get_trigger(interaction.guild_id, id)
        does = []
        if updated.reactions:
            does.append(f"reageert met {updated.reactions}")
        if updated.response:
            does.append(f"{len(updated.response.split('|'))} antwoordvariant(en)")
        await interaction.response.send_message(
            f"✏️ Trigger **#{id}** aangepast: `{updated.pattern}` · " + " · ".join(does),
            ephemeral=True,
        )

    @trigger.command(name="list", description="Toon alle triggers met hun ID, woorden en reacties")
    async def list_cmd(self, interaction: discord.Interaction) -> None:
        rows = self.bot.repo.list_triggers(interaction.guild_id)
        if not rows:
            await interaction.response.send_message(
                "Er zijn nog geen triggers. Gebruik `/trigger add` om er een te maken.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="💬 Triggers", color=discord.Color.blurple())
        lines = []
        for trig in rows:
            parts = [f"**#{trig.id}** — `{trig.pattern}`"]
            if trig.reactions:
                parts.append(f"reageert met {trig.reactions}")
            if trig.response:
                count = len(trig.response.split("|"))
                parts.append(f"{count} antwoordvariant(en)")
            lines.append(" · ".join(parts))
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @trigger.command(name="remove", description="Verwijder een trigger. Kies hem uit de lijst")
    @app_commands.autocomplete(id=_trigger_choices)
    @app_commands.describe(id="Kies de trigger die je wilt verwijderen")
    async def remove_cmd(self, interaction: discord.Interaction, id: int) -> None:
        if self.bot.repo.remove_trigger(interaction.guild_id, id):
            await interaction.response.send_message(f"🗑️ Trigger **#{id}** verwijderd.", ephemeral=True)
        else:
            await interaction.response.send_message(
                f"🚫 Geen trigger gevonden met ID **{id}**.", ephemeral=True
            )


def _reaction_list(reactions: str | None) -> list[str]:
    if not reactions:
        return []
    return [r.strip() for r in reactions.split(",") if r.strip()]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TriggersCog(bot))
