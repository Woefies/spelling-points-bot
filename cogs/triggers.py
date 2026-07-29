"""Triggers cog: react to keywords in messages with a reply, emoji, or both.

Separate from the spelling checkers on purpose — a trigger is a social nudge, not
a mistake, so it awards no points and is configured per guild at runtime rather
than in code.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.variants import compile_phrases, pick_variant

log = logging.getLogger(__name__)

# Seeded by /trigger preset: (pattern, response, reactions)
PK_TRIGGERS: list[tuple[str, str | None, str | None]] = [
    (
        "thuiswerken|thuis werken|thuis aan het werk",
        "Jongens...vergeet niet dat we een kantoormentaliteit hebben bij PK!"
        " | Maximaal 1 dag in de week thuiswerken!"
        " | Thuiswerken? Bij PK is de koffie beter. ☕"
        " | Ik hoor 'thuiswerken'. Ik hoor ook 'maximaal 1 dag per week'. 👀"
        " | De bureaustoel mist je.",
        None,
    ),
    ("kanker|kkr|kanher|kenker", None, "👎,❌"),
]


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

    # -------------------------------------------------------------- commands

    trigger = app_commands.Group(
        name="trigger",
        description="Beheer woorden waar de bot automatisch op reageert met tekst of emoji",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @trigger.command(name="preset", description="Zet de vaste PK-triggers aan: thuiswerken en schelden")
    async def preset_cmd(self, interaction: discord.Interaction) -> None:
        created = 0
        for pattern, response, reactions in PK_TRIGGERS:
            if self.bot.repo.trigger_exists(interaction.guild_id, pattern):
                continue
            self.bot.repo.add_trigger(interaction.guild_id, pattern, response, reactions)
            created += 1

        if not created:
            await interaction.response.send_message(
                "ℹ️ De PK-triggers staan er al. Bekijk ze met `/trigger list`.", ephemeral=True
            )
            return
        await interaction.response.send_message(f"✅ {created} trigger(s) aangemaakt.")

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

        trigger_id = self.bot.repo.add_trigger(interaction.guild_id, woorden, antwoord, reacties)
        await interaction.response.send_message(
            f"✅ Trigger **#{trigger_id}** aangemaakt op: `{woorden}`"
        )

    @trigger.command(name="list", description="Toon alle triggers met hun ID, woorden en reacties")
    async def list_cmd(self, interaction: discord.Interaction) -> None:
        rows = self.bot.repo.list_triggers(interaction.guild_id)
        if not rows:
            await interaction.response.send_message(
                "Er zijn nog geen triggers. Gebruik `/trigger preset` of `/trigger add`."
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
        await interaction.response.send_message(embed=embed)

    @trigger.command(name="remove", description="Verwijder een trigger aan de hand van het ID uit /trigger list")
    @app_commands.describe(id="Het nummer uit /trigger list, bijv. 3")
    async def remove_cmd(self, interaction: discord.Interaction, id: int) -> None:
        if self.bot.repo.remove_trigger(interaction.guild_id, id):
            await interaction.response.send_message(f"🗑️ Trigger **#{id}** verwijderd.")
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
