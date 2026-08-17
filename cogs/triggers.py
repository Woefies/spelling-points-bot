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

from services.punishment import format_minutes, render
from services.variants import compile_phrases, pick_variant, split_variants

log = logging.getLogger(__name__)

CLEAR = "-"  # sentinel in /trigger edit meaning "empty this field"
FALLBACK_RESPONSE = "{user} — let op je woorden."
MAX_LENGTH = 2000  # Discord's per-message limit, applied per | variant

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

            self.bot.repo.log_trigger_hit(message.guild.id, trig.id, message.author.id)

            for emoji in _reaction_list(trig.reactions):
                try:
                    await message.add_reaction(emoji)
                except discord.HTTPException:
                    log.warning("Could not react with %r on trigger %d", emoji, trig.id)

            # At most one reply per message, however many triggers matched —
            # otherwise a single sentence can make the bot spam the channel.
            if trig.response and not replied:
                replied = True
                text = render(
                    pick_variant(trig.response),
                    FALLBACK_RESPONSE,
                    user=message.author.mention,
                    count=self.bot.repo.count_trigger_hits(
                        message.guild.id, trig.id, message.author.id
                    ),
                    minutes=format_minutes(trig.punish_minutes or 0),
                )
                try:
                    # A trigger that mutes has to be allowed to address the person;
                    # one that only jokes should never ping.
                    await message.reply(
                        text,
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions(
                            users=bool(trig.punish_minutes)
                        ),
                    )
                except discord.HTTPException:
                    log.warning("Could not reply for trigger %d", trig.id)

            if trig.punish_minutes:
                # The punishment cog owns every timeout, so /punish mode stays the
                # single switch that governs whether anyone actually gets muted.
                self.bot.dispatch("trigger_punishment", message, trig)

    # --------------------------------------------------------- autocomplete

    async def _trigger_choices(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[int]]:
        term = current.lower()
        choices = []
        for trig in self.bot.repo.list_triggers(interaction.guild_id):
            what = trig.reactions or (trig.response or "").split("|")[0].strip()
            if trig.punish_minutes:
                what = f"⏱️{trig.punish_minutes}m {what}".strip()
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
        words="Waar de bot op let. Meerdere schrijfwijzen met |: thuiswerken|thuis werken",
        response="Wat de bot terugzegt. Varianten met | zodat hij afwisselt. Leeg = niets zeggen",
        reactions="Emoji onder het bericht, gescheiden door kommas. Bijvoorbeeld: 👎,❌",
        minutes="Timeout in minuten bij dit woord. Leeg laten voor geen straf",
    )
    async def add_cmd(
        self,
        interaction: discord.Interaction,
        words: str,
        response: str | None = None,
        reactions: str | None = None,
        minutes: app_commands.Range[int, 1, 1440] | None = None,
    ) -> None:
        if not response and not reactions and not minutes:
            await interaction.response.send_message(
                "🚫 Vul minstens `response`, `reactions` of `minutes` in, "
                "anders doet de trigger niets.",
                ephemeral=True,
            )
            return

        too_long = _oversized(response)
        if too_long:
            await interaction.response.send_message(
                f"🚫 Variant {too_long[0]} is **{too_long[1]}** tekens. Discord staat er "
                f"{MAX_LENGTH} toe per bericht, dus die zou nooit verstuurd worden.\n"
                "_Knip hem korter, of splits met een `|` in meerdere varianten._",
                ephemeral=True,
            )
            return

        if self.bot.repo.trigger_exists(interaction.guild_id, words):
            await interaction.response.send_message(
                f"🚫 Er bestaat al een trigger op `{words}`. Bekijk ze met `/trigger list`.",
                ephemeral=True,
            )
            return

        trigger_id = self.bot.repo.add_trigger(
            interaction.guild_id, words, response, reactions, minutes
        )
        tail = f"\n⚠️ Dempt **{format_minutes(minutes)}** — {_punish_note(self.bot, interaction.guild_id)}" if minutes else ""
        await interaction.response.send_message(
            f"✅ Trigger **#{trigger_id}** aangemaakt op: `{words}`{tail}",
            ephemeral=True,
        )

    @trigger.command(name="edit", description="Wijzig de woorden, het antwoord of de reacties van een trigger")
    @app_commands.autocomplete(id=_trigger_choices)
    @app_commands.describe(
        id="Kies de trigger die je wilt aanpassen",
        words="Nieuwe schrijfwijzen, gescheiden met |. Leeg laten = ongewijzigd",
        response="Nieuw antwoord, varianten met |. Typ een - om het antwoord te wissen",
        reactions="Nieuwe emoji, gescheiden door kommas. Typ een - om ze te wissen",
        minutes="Timeout in minuten. Typ 0 om de straf te verwijderen",
    )
    async def edit_cmd(
        self,
        interaction: discord.Interaction,
        id: int,
        words: str | None = None,
        response: str | None = None,
        reactions: str | None = None,
        minutes: app_commands.Range[int, 0, 1440] | None = None,
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
        if words is not None:
            changes["pattern"] = words
        if response is not None:
            changes["response"] = None if response.strip() == CLEAR else response
        if reactions is not None:
            changes["reactions"] = None if reactions.strip() == CLEAR else reactions
        if minutes is not None:
            # 0 rather than "-" here: the field is numeric, so a sentinel string
            # would not survive Discord's own validation.
            changes["punish_minutes"] = minutes or None

        if not changes:
            await interaction.response.send_message(
                "🚫 Vul minstens één veld in dat je wilt wijzigen.", ephemeral=True
            )
            return

        too_long = _oversized(changes.get("response"))
        if too_long:
            await interaction.response.send_message(
                f"🚫 Variant {too_long[0]} is **{too_long[1]}** tekens, en Discord staat "
                f"er {MAX_LENGTH} toe per bericht.",
                ephemeral=True,
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
        if updated.punish_minutes:
            does.append(f"dempt {format_minutes(updated.punish_minutes)}")
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
            if trig.punish_minutes:
                parts.append(f"⏱️ dempt {format_minutes(trig.punish_minutes)}")
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


def _oversized(response: str | None) -> tuple[int, int] | None:
    """First variant that could never be sent, as (position, length).

    Checked when the trigger is written rather than when it fires: a send that
    fails at fire time is swallowed and logged, so the trigger would look broken
    for no visible reason.
    """
    if not response:
        return None
    for index, variant in enumerate(split_variants(response), start=1):
        if len(variant) > MAX_LENGTH:
            return index, len(variant)
    return None


def _punish_note(bot, guild_id: int) -> str:
    """Say plainly whether this trigger will actually mute anyone yet."""
    from cogs.punishment import CONFIG_MODE, MODE_LABELS

    mode = bot.repo.get_config(guild_id, CONFIG_MODE) or "off"
    if mode == "mute":
        return "straffen staan aan, dit dempt echt"
    return f"straffen staan op **{MODE_LABELS[mode]}**, dus er wordt nog niemand gedempt"


def _reaction_list(reactions: str | None) -> list[str]:
    if not reactions:
        return []
    return [r.strip() for r in reactions.split(",") if r.strip()]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TriggersCog(bot))
