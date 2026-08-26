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

from services.evasion import near_misses, obfuscations
from services.forms import read_bool, read_optional_int, write_bool
from services.punishment import format_minutes, render
from services.testmode import MARKER, MUTED, TEST, state_for
from services.variants import compile_phrases, pick_variant, split_variants

log = logging.getLogger(__name__)

CLEAR = "-"  # sentinel in /trigger edit meaning "empty this field"
CONFIG_OBFUSCATION = "trigger_obfuscation"
FALLBACK_RESPONSE = "{user} — let op je woorden."
MAX_LENGTH = 2000  # Discord's per-message limit, applied per | variant

class TriggersCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return

        config = self.bot.repo.config_for(message.guild.id)
        where = state_for(config, message.channel)
        if where == MUTED:
            return
        testing = where == TEST

        replied = False
        for trig in self.bot.repo.list_triggers(message.guild.id):
            dodge = None
            if not compile_phrases(trig.pattern).search(message.content):
                dodge = await self._dodge(message, trig, config)
                if dodge is None:
                    continue

            if not testing:
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
                count = self.bot.repo.count_trigger_hits(
                    message.guild.id, trig.id, message.author.id
                )
                text = render(
                    pick_variant(trig.response),
                    FALLBACK_RESPONSE,
                    user=message.author.mention,
                    count=count,
                    minutes=format_minutes(trig.punish_minutes or 0),
                )

                # A generated line replaces the stored one only when the AI cog
                # is loaded, switched on, in budget and actually answers. Every
                # other path keeps the text above, so the bot never falls silent.
                ai = self.bot.get_cog("AICog")
                if ai is not None:
                    generated = await ai.reply_for(
                        message.guild.id, trig.pattern, count, message.content
                    )
                    if generated:
                        text = f"{message.author.mention} {generated}"

                if dodge:
                    # Name the word. Someone muted for a word they did not
                    # literally type deserves to see what was read into it.
                    text += f"\n_(`{dodge}` gelezen als omzeiling van `{trig.pattern.split('|')[0]}`)_"

                if testing:
                    # Say what the trigger would have cost, since the timeout
                    # itself is exactly what the sandbox is holding back.
                    if trig.punish_minutes:
                        text += f"\n_(zou {format_minutes(trig.punish_minutes)} dempen)_"
                    text += f"\n{MARKER}"
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

            if trig.punish_minutes and not testing:
                # The punishment cog owns every timeout, so /punish mode stays the
                # single switch that governs whether anyone actually gets muted.
                self.bot.dispatch("trigger_punishment", message, trig)

    # -------------------------------------------------------------- evasion

    async def _dodge(self, message: discord.Message, trig, config: dict) -> str | None:
        """The word this message used to dodge `trig`, if any.

        Two tiers, cheapest first. The free one is deterministic and offline; the
        paid one only ever sees words the free one could not settle, that the
        dictionaries do not recognise, and that nobody whitelisted.
        """
        if config.get(CONFIG_OBFUSCATION) == "1":
            hits = obfuscations(message.content, trig.pattern)
            if hits:
                return hits[0]

        # Per trigger, and only then per guild. A trigger nobody opted in stays
        # a plain word-boundary match however the guild has AI configured.
        if not trig.watch_evasion:
            return None

        ai = self.bot.get_cog("AICog")
        if ai is None or not ai.evasion_on(message.guild.id):
            return None

        skip = {w.lower() for w in self.bot.repo.get_whitelist(message.guild.id)}
        # Per guild, via /ai limits: without a ceiling here a single long message
        # could spend a whole day's budget by itself.
        limit = ai.candidates(message.guild.id)
        for word in near_misses(message.content, trig.pattern, skip)[:limit]:
            if self._is_real_word(word):
                continue
            if await ai.evasion_for(message.guild.id, trig.pattern, word, message.content):
                return word
        return None

    def _watch_note(self, guild_id: int) -> str:
        """Say plainly whether watching this trigger does anything yet.

        Two switches have to line up — this trigger, and /ai evasion for the
        guild — so the half that is still off names itself here rather than
        being discovered later as "the bot just does not react to it".
        """
        ai = self.bot.get_cog("AICog")
        if ai is not None and ai.evasion_on(guild_id):
            return "👁️ De AI beoordeelt verdraaide schrijfwijzen van dit woord."
        return (
            "👁️ Genoteerd, maar er gebeurt nog niets: `/ai evasion` staat uit. "
            "Zet die aan om dit te laten werken."
        )

    def _is_real_word(self, word: str) -> bool:
        """Dictionary check, and never a reason to abort on failure."""
        from services.checkers import REGISTRY

        checker = REGISTRY.get("spelling")
        if checker is None:
            return False
        try:
            return checker.knows(word, {"hunspell_dir": self.bot.settings.hunspell_dir})
        except Exception:
            log.exception("Dictionary lookup failed for %r", word)
            return False

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
            if trig.watch_evasion:
                what = f"👁️ {what}".strip()
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
        watch="Laat de AI ook verdraaide schrijfwijzen hiervan opsporen. Standaard uit",
    )
    async def add_cmd(
        self,
        interaction: discord.Interaction,
        words: str,
        response: str | None = None,
        reactions: str | None = None,
        minutes: app_commands.Range[int, 1, 1440] | None = None,
        watch: bool = False,
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
            interaction.guild_id, words, response, reactions, minutes, watch
        )
        tail = f"\n⚠️ Dempt **{format_minutes(minutes)}** — {_punish_note(self.bot, interaction.guild_id)}" if minutes else ""
        if watch:
            tail += "\n" + self._watch_note(interaction.guild_id)
        await interaction.response.send_message(
            f"✅ Trigger **#{trigger_id}** aangemaakt op: `{words}`{tail}",
            ephemeral=True,
        )

    @trigger.command(name="edit", description="Wijzig de woorden, het antwoord of de reacties van een trigger")
    @app_commands.autocomplete(id=_trigger_choices)
    @app_commands.describe(
        id="Kies de trigger. Vul verder niets in voor een invulvenster",
        words="Nieuwe schrijfwijzen, gescheiden met |. Leeg laten = ongewijzigd",
        response="Nieuw antwoord, varianten met |. Typ een - om het antwoord te wissen",
        reactions="Nieuwe emoji, gescheiden door kommas. Typ een - om ze te wissen",
        minutes="Timeout in minuten. Typ 0 om de straf te verwijderen",
        watch="Of de AI verdraaide schrijfwijzen van dit woord mag opsporen",
    )
    async def edit_cmd(
        self,
        interaction: discord.Interaction,
        id: int,
        words: str | None = None,
        response: str | None = None,
        reactions: str | None = None,
        minutes: app_commands.Range[int, 0, 1440] | None = None,
        watch: bool | None = None,
    ) -> None:
        existing = self.bot.repo.get_trigger(interaction.guild_id, id)
        if existing is None:
            await interaction.response.send_message(
                f"🚫 Geen trigger met ID **{id}**. Bekijk ze met `/trigger list`.", ephemeral=True
            )
            return

        # Only the ID given: open the form with the current values filled in,
        # rather than making someone retype what they cannot see. Naming any
        # other option keeps the one-line path, which stays copy-pasteable.
        if all(v is None for v in (words, response, reactions, minutes, watch)):
            await interaction.response.send_modal(TriggerForm(self, existing))
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
        if watch is not None:
            changes["watch_evasion"] = 1 if watch else 0

        if not changes:
            await interaction.response.send_message(
                "🚫 Vul minstens één veld in dat je wilt wijzigen.", ephemeral=True
            )
            return

        problem = _validate(existing, changes)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return

        self.bot.repo.update_trigger(interaction.guild_id, id, changes)
        await interaction.response.send_message(
            self._summary(interaction.guild_id, id), ephemeral=True
        )

    def _summary(self, guild_id: int, trigger_id: int) -> str:
        """What the trigger now does, in one line."""
        updated = self.bot.repo.get_trigger(guild_id, trigger_id)
        does = []
        if updated.reactions:
            does.append(f"reageert met {updated.reactions}")
        if updated.response:
            does.append(f"{len(updated.response.split('|'))} antwoordvariant(en)")
        if updated.punish_minutes:
            does.append(f"dempt {format_minutes(updated.punish_minutes)}")
        if updated.watch_evasion:
            does.append("AI let op omzeiling")
        tail = "\n" + self._watch_note(guild_id) if updated.watch_evasion else ""
        return (
            f"✏️ Trigger **#{trigger_id}** aangepast: `{updated.pattern}` · "
            + " · ".join(does)
            + tail
        )

    @trigger.command(name="obfuscation", description="Ook reageren op verdraaide schrijfwijzen zoals br3nt")
    @app_commands.describe(
        enabled="Aan vangt cijfers voor letters, herhaalde letters en b r e n t. Geen AI nodig"
    )
    async def obfuscation_cmd(self, interaction: discord.Interaction, enabled: bool) -> None:
        self.bot.repo.set_config(
            interaction.guild_id, CONFIG_OBFUSCATION, "1" if enabled else None
        )
        if enabled:
            text = (
                "✅ Verdraaide schrijfwijzen tellen mee. `br3nt`, `brenttt`, `b r e n t` "
                "en `b-r-e-n-t` gelden nu als een gewone treffer.\n"
                "_Dit is een vaste regel, geen AI: het woord moet na normaliseren "
                "letterlijk hetzelfde zijn. Voor gevallen als `brentify` is "
                "`/ai evasion` nodig._"
            )
        else:
            text = "🛑 Alleen exacte treffers tellen weer."
        await interaction.response.send_message(text, ephemeral=True)

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
            if trig.watch_evasion:
                parts.append("👁️ AI let op omzeiling")
            lines.append(" · ".join(parts))
        embed.description = "\n".join(lines)
        if any(t.watch_evasion for t in rows):
            embed.set_footer(text="👁️ = de AI beoordeelt ook verdraaide schrijfwijzen")
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


class TriggerForm(discord.ui.Modal):
    """The edit screen for one trigger, pre-filled with what it holds now.

    A lone "-" means nothing here, unlike the slash command: in a form you can
    see every field, so an empty box already says "empty this" unambiguously.
    """

    def __init__(self, cog: "TriggersCog", trig) -> None:
        super().__init__(title=f"Trigger #{trig.id} aanpassen")
        self.cog = cog
        self.trigger_id = trig.id

        self.words = discord.ui.TextInput(
            label="Woorden",
            default=trig.pattern,
            placeholder="thuiswerken|thuis werken",
            max_length=500,
        )
        self.response = discord.ui.TextInput(
            label="Antwoord (leeg = geen antwoord)",
            style=discord.TextStyle.paragraph,
            default=trig.response or "",
            placeholder="Varianten scheiden met | · {user} {count} {minutes}",
            required=False,
            max_length=2000,
        )
        self.reactions = discord.ui.TextInput(
            label="Emoji (leeg = geen)",
            default=trig.reactions or "",
            placeholder="👀,❌",
            required=False,
            max_length=200,
        )
        self.minutes = discord.ui.TextInput(
            label="Timeout in minuten (leeg = geen straf)",
            default=str(trig.punish_minutes) if trig.punish_minutes else "",
            placeholder="5",
            required=False,
            max_length=4,
        )
        self.watch = discord.ui.TextInput(
            label="AI let op omzeiling? ja / nee",
            default=write_bool(bool(trig.watch_evasion)),
            required=False,
            max_length=10,
        )
        for field in (self.words, self.response, self.reactions, self.minutes, self.watch):
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        minutes = read_optional_int(self.minutes.value, 1, 1440)
        if isinstance(minutes, str):
            await interaction.response.send_message(f"🚫 Timeout: {minutes}", ephemeral=True)
            return

        watch = read_bool(self.watch.value)
        if watch is None:
            await interaction.response.send_message(
                f"🚫 Vul bij omzeiling `ja` of `nee` in, niet `{self.watch.value[:30]}`.",
                ephemeral=True,
            )
            return

        changes = {
            "pattern": self.words.value.strip(),
            "response": self.response.value.strip() or None,
            "reactions": self.reactions.value.strip() or None,
            "punish_minutes": minutes,
            "watch_evasion": 1 if watch else 0,
        }

        existing = self.cog.bot.repo.get_trigger(interaction.guild_id, self.trigger_id)
        if existing is None:
            await interaction.response.send_message(
                f"🚫 Trigger **#{self.trigger_id}** bestaat niet meer.", ephemeral=True
            )
            return

        problem = _validate(existing, changes)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return

        self.cog.bot.repo.update_trigger(interaction.guild_id, self.trigger_id, changes)
        await interaction.response.send_message(
            self.cog._summary(interaction.guild_id, self.trigger_id), ephemeral=True
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        # Without this a raising form shows Discord's own blank failure, which
        # says nothing about which field was the problem.
        log.exception("Trigger form failed")
        message = f"⚠️ Opslaan mislukt: {type(error).__name__}: {error}"[:400]
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


def _validate(existing, changes: dict) -> str | None:
    """Why this edit cannot be saved, or None if it can.

    Shared by the slash command and the form on purpose: two copies of these
    rules would drift, and the one that drifts is the one nobody is testing.
    """
    too_long = _oversized(changes.get("response"))
    if too_long:
        return (
            f"🚫 Variant {too_long[0]} is **{too_long[1]}** tekens, en Discord staat "
            f"er {MAX_LENGTH} toe per bericht."
        )

    if not changes.get("pattern", existing.pattern).strip():
        return "🚫 `woorden` mag niet leeg zijn — dan weet de bot nergens op te letten."

    response = changes.get("response", existing.response)
    reactions = changes.get("reactions", existing.reactions)
    if not response and not reactions:
        return (
            "🚫 Dan blijft er niets over: houd een `antwoord` of `reacties` over, "
            "anders doet de trigger niets. Verwijderen kan met `/trigger remove`."
        )
    return None


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
