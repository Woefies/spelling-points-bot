"""AI cog: configure generated trigger replies.

Off by default and per guild. Every setting lives in the database, so the voice
can change without a rebuild — the same reason no reminder or trigger text sits
in the code.
"""

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from services.ai import (
    DEFAULT_BUDGET,
    DEFAULT_CANDIDATES,
    DEFAULT_PERSONA,
    MAX_CANDIDATES,
    MAX_TIMEOUT,
    MIN_CANDIDATES,
    MIN_TIMEOUT,
    TIMEOUT_SECONDS,
    KEY_NAME,
    api_key,
    clamp,
    key_state,
    build_prompt,
    format_usage,
    generate,
    judge_evasion,
    parse_usage,
)

log = logging.getLogger(__name__)

# One key per feature rather than one master switch: writing a joke and deciding
# that someone dodged a filter are different powers, and a guild that wants the
# first must not silently get the second.
CONFIG_REPLIES = "ai_replies"
CONFIG_EVASION = "ai_evasion"
CONFIG_PERSONA = "ai_persona"
CONFIG_BUDGET = "ai_budget"
CONFIG_TIMEOUT = "ai_timeout"
CONFIG_CANDIDATES = "ai_candidates"
CONFIG_USAGE = "ai_usage"
CONFIG_SEND_MESSAGE = "ai_send_message"

RESET = "-"


class AICog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Logged at load rather than on first use: "is the key even reaching the
        # container?" is the first question every time, and the startup log is
        # the one place someone with shell access is already looking.
        log.info(
            "AI cog loaded, ANTHROPIC_API_KEY %s",
            "present" if api_key() else "MISSING — /ai stays off",
        )

    # ------------------------------------------------------------- used by triggers

    def replies_on(self, guild_id: int) -> bool:
        return self.bot.repo.get_config(guild_id, CONFIG_REPLIES) == "1"

    def evasion_on(self, guild_id: int) -> bool:
        return self.bot.repo.get_config(guild_id, CONFIG_EVASION) == "1"

    def persona(self, guild_id: int) -> str:
        return self.bot.repo.get_config(guild_id, CONFIG_PERSONA) or DEFAULT_PERSONA

    def budget(self, guild_id: int) -> int:
        raw = self.bot.repo.get_config(guild_id, CONFIG_BUDGET)
        try:
            return int(raw) if raw else DEFAULT_BUDGET
        except ValueError:
            return DEFAULT_BUDGET

    def timeout(self, guild_id: int) -> float:
        raw = self.bot.repo.get_config(guild_id, CONFIG_TIMEOUT)
        try:
            return clamp(float(raw), MIN_TIMEOUT, MAX_TIMEOUT) if raw else TIMEOUT_SECONDS
        except ValueError:
            return TIMEOUT_SECONDS

    def candidates(self, guild_id: int) -> int:
        """How many words from one message may be sent to the model."""
        raw = self.bot.repo.get_config(guild_id, CONFIG_CANDIDATES)
        try:
            return int(clamp(int(raw), MIN_CANDIDATES, MAX_CANDIDATES)) if raw else DEFAULT_CANDIDATES
        except ValueError:
            return DEFAULT_CANDIDATES

    def used_today(self, guild_id: int) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return parse_usage(self.bot.repo.get_config(guild_id, CONFIG_USAGE), today)

    def _spend(self, guild_id: int) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        used = self.used_today(guild_id)
        self.bot.repo.set_config(guild_id, CONFIG_USAGE, format_usage(today, used + 1))

    async def reply_for(self, guild_id: int, pattern: str, count: int, content: str) -> str | None:
        """A generated reply, or None so the caller uses its own stored text."""
        if not self.replies_on(guild_id) or not api_key():
            return None
        if self.used_today(guild_id) >= self.budget(guild_id):
            log.info("AI budget spent for guild %s", guild_id)
            return None

        send_message = self.bot.repo.get_config(guild_id, CONFIG_SEND_MESSAGE) == "1"
        # Count the call before making it: a failed call still cost latency, and
        # a budget that only counts successes cannot stop a failing loop.
        self._spend(guild_id)
        return await generate(
            self.persona(guild_id),
            build_prompt(pattern, count, content if send_message else None),
            self.timeout(guild_id),
        )

    async def evasion_for(self, guild_id: int, pattern: str, word: str, content: str) -> bool:
        """Whether `word` is a deliberate dodge of `pattern`.

        False on every uncertain path — feature off, no key, budget spent, call
        failed, answer unreadable. The consequence of a True here is somebody
        being muted, so "I don't know" can only ever mean no.
        """
        if not self.evasion_on(guild_id) or not api_key():
            return False

        cached = self.bot.repo.get_evasion_verdict(guild_id, pattern, word)
        if cached is not None:
            return cached

        if self.used_today(guild_id) >= self.budget(guild_id):
            log.info("AI budget spent for guild %s", guild_id)
            return False

        send_message = self.bot.repo.get_config(guild_id, CONFIG_SEND_MESSAGE) == "1"
        self._spend(guild_id)
        verdict = await judge_evasion(
            pattern, word, content if send_message else None, self.timeout(guild_id)
        )
        if verdict is None:
            # Deliberately not cached: a non-answer is not a verdict, and storing
            # it would turn one bad call into a permanent one.
            return False

        self.bot.repo.set_evasion_verdict(guild_id, pattern, word, verdict)
        log.info("Evasion verdict %s: %r vs %r in guild %s", verdict, word, pattern, guild_id)
        return verdict

    # -------------------------------------------------------------------- commands

    ai = app_commands.Group(
        name="ai",
        description="Laat de bot trigger-antwoorden zelf schrijven",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    def _key_problem(self) -> str:
        """Say which way the key is missing, since the fixes differ."""
        state, similar = key_state()
        if state == "empty":
            text = f"**staat leeg** — `{KEY_NAME}=` zonder waarde erachter"
        else:
            text = "**bereikt de bot niet**"
        if similar:
            names = ", ".join(f"`{n}`" for n in similar[:5])
            text += f"\n  ⚠️ Wel gevonden, met een andere naam: {names}"
        return text

    def _no_key(self) -> str:
        """Why the key is missing is nearly always one of two things.

        Naming both here saves the round trip to whoever has shell access, which
        on this deployment is one person who is not always available.
        """
        return (
            f"🚫 De bot ziet geen `{KEY_NAME}` — {self._key_problem()}\n"
            "Twee mogelijke oorzaken:\n"
            "1. De sleutel staat nog niet in de `.env` naast `docker-compose.yml`, "
            "of de regel begint met een `#`.\n"
            "2. De sleutel staat er wél, maar de container draait nog met de oude "
            "omgeving. **Herstarten is niet genoeg** — `.env` wordt alleen gelezen "
            "als de container opnieuw wordt aangemaakt:\n"
            "```\ndocker compose up -d --force-recreate\n```\n"
            "_Controleren: `docker exec spellbot printenv ANTHROPIC_API_KEY` — "
            "lege uitvoer betekent dat hij het proces niet bereikt._"
        )

    @ai.command(name="replies", description="Laat de AI het antwoord op een trigger schrijven")
    @app_commands.describe(enabled="Uit betekent: altijd de vaste tekst van de trigger")
    async def replies_cmd(self, interaction: discord.Interaction, enabled: bool) -> None:
        if enabled and not api_key():
            await interaction.response.send_message(self._no_key(), ephemeral=True)
            return
        self.bot.repo.set_config(
            interaction.guild_id, CONFIG_REPLIES, "1" if enabled else None
        )
        if enabled:
            text = (
                f"✅ AI-antwoorden aan, maximaal **{self.budget(interaction.guild_id)}** per dag.\n"
                "_Lukt het niet, dan valt de bot terug op de vaste tekst van de trigger._"
            )
        else:
            text = "🛑 AI-antwoorden uit. Triggers gebruiken weer hun vaste tekst."
        await interaction.response.send_message(text, ephemeral=True)

    @ai.command(name="evasion", description="Laat de AI beoordelen of iemand een trigger omzeilt")
    @app_commands.describe(enabled="Aan laat de AI oordelen over woorden die op een trigger lijken")
    async def evasion_cmd(self, interaction: discord.Interaction, enabled: bool) -> None:
        if enabled and not api_key():
            await interaction.response.send_message(self._no_key(), ephemeral=True)
            return
        self.bot.repo.set_config(
            interaction.guild_id, CONFIG_EVASION, "1" if enabled else None
        )
        if not enabled:
            await interaction.response.send_message(
                "🛑 AI-omzeilingscheck uit. Alleen exacte treffers tellen nog "
                "(en de gratis check, als die aanstaat).",
                ephemeral=True,
            )
            return

        # This is the one AI feature whose verdict can end in a timeout, so it
        # says so plainly instead of leaving that to be discovered.
        from cogs.punishment import CONFIG_MODE, MODE_LABELS

        mode = self.bot.repo.get_config(interaction.guild_id, CONFIG_MODE) or "off"
        watched = [t for t in self.bot.repo.list_triggers(interaction.guild_id) if t.watch_evasion]
        if not watched:
            # On, but pointed at nothing. Saying so here is the difference between
            # a setting that looks broken and one that is simply not aimed yet.
            await interaction.response.send_message(
                "✅ AI-omzeilingscheck aan — maar **geen enkele trigger staat aan** om "
                "in de gaten gehouden te worden, dus er gebeurt nog niets.\n"
                "_Zet 'm per trigger aan met `/trigger edit id:… watch:True`. "
                "Bekijk ze met `/trigger list`._",
                ephemeral=True,
            )
            return

        names = ", ".join(f"`{t.pattern.split('|')[0]}`" for t in watched[:10])
        await interaction.response.send_message(
            f"✅ AI-omzeilingscheck aan voor **{len(watched)}** trigger(s): {names}\n"
            "Woorden die *lijken* op die triggers maar er niet gelijk aan zijn, "
            "worden aan de AI voorgelegd.\n"
            f"⚠️ Een oordeel telt als een gewone treffer, dus straffen lopen via "
            f"`/punish` — die staat nu op **{MODE_LABELS[mode]}**.\n"
            "_Zet `/punish mode` eerst op waarschuwen en kijk een paar dagen mee. "
            "Een verkeerd oordeel corrigeer je met `/ai forget`._",
            ephemeral=True,
        )

    @ai.command(name="off", description="Zet alle AI-functies in een keer uit")
    async def off_cmd(self, interaction: discord.Interaction) -> None:
        for key in (CONFIG_REPLIES, CONFIG_EVASION):
            self.bot.repo.set_config(interaction.guild_id, key, None)
        await interaction.response.send_message(
            "🛑 Alle AI-functies uit. De bot werkt weer volledig op vaste teksten "
            "en exacte treffers.",
            ephemeral=True,
        )

    @ai.command(name="forget", description="Vergeet een eerder AI-oordeel over een woord")
    @app_commands.describe(word="Het woord dat opnieuw beoordeeld mag worden. Een - wist alles")
    async def forget_cmd(self, interaction: discord.Interaction, word: str) -> None:
        target = None if word.strip() == RESET else word.strip()
        removed = self.bot.repo.forget_evasion_verdict(interaction.guild_id, target)
        if not removed:
            await interaction.response.send_message(
                f"ℹ️ Er stond geen oordeel over `{word}` opgeslagen.", ephemeral=True
            )
            return
        where = "alle oordelen" if target is None else f"het oordeel over `{target}`"
        await interaction.response.send_message(
            f"🧹 {removed} × {where} gewist. Het woord wordt bij de volgende keer "
            "opnieuw beoordeeld.",
            ephemeral=True,
        )

    @ai.command(name="verdicts", description="Toon welke woorden de AI als omzeiling ziet")
    async def verdicts_cmd(self, interaction: discord.Interaction) -> None:
        rows = self.bot.repo.list_evasion_verdicts(interaction.guild_id)
        if not rows:
            await interaction.response.send_message(
                "Er is nog niets beoordeeld.", ephemeral=True
            )
            return
        lines = [
            f"{'🚫' if verdict else '✅'} `{word}` — trigger `{pattern}`"
            for pattern, word, verdict in rows[:40]
        ]
        tail = f"\n_… en nog {len(rows) - 40}._" if len(rows) > 40 else ""
        await interaction.response.send_message(
            "🧠 **Oordelen**\n🚫 = omzeiling, ✅ = gewoon woord\n"
            + "\n".join(lines) + tail
            + "\n_Corrigeren met `/ai forget`._",
            ephemeral=True,
        )

    @ai.command(name="persona", description="Beschrijf hoe de bot moet klinken")
    @app_commands.describe(text="Leeg laten opent een invulvenster. Een - zet de standaard terug")
    async def persona_cmd(
        self, interaction: discord.Interaction, text: str | None = None
    ) -> None:
        # Nothing given: open the form with the current persona in it. This is
        # the longest text anyone writes in this bot, and rewriting it blind in a
        # one-line box is how good wording gets lost.
        if text is None:
            await interaction.response.send_modal(
                PersonaForm(self, self.persona(interaction.guild_id))
            )
            return

        if text.strip() == RESET:
            self.bot.repo.set_config(interaction.guild_id, CONFIG_PERSONA, None)
            await interaction.response.send_message(
                f"✅ Standaardpersona hersteld:\n>>> {DEFAULT_PERSONA}", ephemeral=True
            )
            return
        self.bot.repo.set_config(interaction.guild_id, CONFIG_PERSONA, text)
        await interaction.response.send_message(
            f"✅ Persona opgeslagen:\n>>> {text[:1500]}\n\n"
            "_Probeer 'm met `/ai test`._",
            ephemeral=True,
        )

    @ai.command(name="budget", description="Maximaal aantal AI-aanroepen per dag")
    @app_commands.describe(amount="Op = terugval naar de vaste teksten. 0 zet de AI stil. Standaard 50")
    async def budget_cmd(
        self, interaction: discord.Interaction, amount: app_commands.Range[int, 0, 1000]
    ) -> None:
        self.bot.repo.set_config(interaction.guild_id, CONFIG_BUDGET, str(amount))
        note = "" if amount else "\n_Op 0 doet de AI niets meer; alles valt terug op vaste teksten._"
        await interaction.response.send_message(
            f"✅ Dagbudget staat op **{amount}** aanroepen per dag."
            f"{note}\n_Vandaag al gebruikt: {self.used_today(interaction.guild_id)}._",
            ephemeral=True,
        )

    @ai.command(name="limits", description="Stel de wachttijd en het aantal woorden per bericht in")
    @app_commands.describe(
        timeout="Seconden wachten op de AI. Daarna de vaste tekst. Standaard 5",
        candidates="Hoeveel woorden uit een bericht beoordeeld mogen worden. Standaard 3",
    )
    async def limits_cmd(
        self,
        interaction: discord.Interaction,
        timeout: app_commands.Range[float, MIN_TIMEOUT, MAX_TIMEOUT] | None = None,
        candidates: app_commands.Range[int, MIN_CANDIDATES, MAX_CANDIDATES] | None = None,
    ) -> None:
        gid = interaction.guild_id
        if timeout is not None:
            self.bot.repo.set_config(gid, CONFIG_TIMEOUT, str(round(timeout, 1)))
        if candidates is not None:
            self.bot.repo.set_config(gid, CONFIG_CANDIDATES, str(candidates))

        changed = "✅ Aangepast.\n" if (timeout is not None or candidates is not None) else ""
        await interaction.response.send_message(
            f"{changed}⏱️ **Limieten**\n"
            f"• Dagbudget: **{self.budget(gid)}** aanroepen _(`/ai budget`)_\n"
            f"• Wachttijd: **{self.timeout(gid):g}** seconden\n"
            f"• Woorden per bericht: **{self.candidates(gid)}**\n\n"
            "_Wachttijd is hoe lang het kanaal maximaal op de AI wacht; daarna gaat "
            "de vaste tekst eruit. Woorden per bericht begrenst wat één lang bericht "
            "van je dagbudget kan opsouperen._",
            ephemeral=True,
        )

    @ai.command(name="context", description="Mag het model het bericht zelf zien, of alleen het woord?")
    @app_commands.describe(
        send_message="Aan stuurt het bericht mee naar Anthropic. Uit alleen het trefwoord"
    )
    async def context_cmd(self, interaction: discord.Interaction, send_message: bool) -> None:
        self.bot.repo.set_config(
            interaction.guild_id, CONFIG_SEND_MESSAGE, "1" if send_message else None
        )
        if send_message:
            text = (
                "✅ Het model krijgt het bericht mee. Antwoorden worden gerichter, maar "
                "**berichten van collega's verlaten hiermee de server** richting Anthropic."
            )
        else:
            text = (
                "✅ Het model krijgt alleen het trefwoord en hoe vaak iemand het zei. "
                "Berichtinhoud blijft op de NAS."
            )
        await interaction.response.send_message(text, ephemeral=True)

    @ai.command(name="test", description="Genereer nu een voorbeeldantwoord met de huidige persona")
    @app_commands.describe(word="Trefwoord om mee te testen, bijvoorbeeld thuiswerken")
    async def test_cmd(self, interaction: discord.Interaction, word: str) -> None:
        if not api_key():
            await interaction.response.send_message(self._no_key(), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        # Deliberately bypasses the on/off check so the persona can be tuned
        # before switching it on for the channel. It does spend budget.
        self._spend(interaction.guild_id)
        text = await generate(
            self.persona(interaction.guild_id),
            build_prompt(word, 3, None),
            self.timeout(interaction.guild_id),
        )
        await interaction.followup.send(
            f"🤖 {text}" if text else
            "🚫 Geen antwoord gekregen. Sleutel geldig? Budget op? Kijk in de logs.",
            ephemeral=True,
        )

    @ai.command(name="status", description="Toon of AI aanstaat, het verbruik en de persona")
    async def status_cmd(self, interaction: discord.Interaction) -> None:
        gid = interaction.guild_id
        key = "aanwezig" if api_key() else self._key_problem()
        content = "bericht wordt meegestuurd" if self.bot.repo.get_config(gid, CONFIG_SEND_MESSAGE) == "1" \
            else "alleen het trefwoord"
        judged = len(self.bot.repo.list_evasion_verdicts(gid))
        watched = sum(1 for t in self.bot.repo.list_triggers(gid) if t.watch_evasion)
        await interaction.response.send_message(
            f"🤖 API-sleutel {key}\n"
            f"• Antwoorden schrijven: **{'aan' if self.replies_on(gid) else 'uit'}**\n"
            f"• Omzeiling beoordelen: **{'aan' if self.evasion_on(gid) else 'uit'}** "
            f"voor {watched} trigger(s), {judged} woord(en) beoordeeld\n"
            f"• Vandaag gebruikt: **{self.used_today(gid)}** van **{self.budget(gid)}**\n"
            f"• Wachttijd **{self.timeout(gid):g}s** · max **{self.candidates(gid)}** "
            f"woord(en) per bericht _(`/ai limits`)_\n"
            f"• Context: {content}\n\n"
            f"**Persona:**\n>>> {self.persona(gid)[:1500]}",
            ephemeral=True,
        )



class PersonaForm(discord.ui.Modal):
    """The persona, in a box big enough to actually read it back."""

    def __init__(self, cog: "AICog", current: str) -> None:
        super().__init__(title="Persona aanpassen")
        self.cog = cog
        self.text = discord.ui.TextInput(
            label="Hoe de bot schrijft",
            style=discord.TextStyle.paragraph,
            default=current,
            placeholder="Lengte, toon, eigenaardigheden, en twee voorbeeldzinnen",
            max_length=3000,
        )
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        value = self.text.value.strip()
        if not value:
            await interaction.response.send_message(
                "🚫 De persona mag niet leeg zijn. Wil je de standaard terug: "
                "`/ai persona text:-`.",
                ephemeral=True,
            )
            return
        self.cog.bot.repo.set_config(interaction.guild_id, CONFIG_PERSONA, value)
        await interaction.response.send_message(
            f"✅ Persona opgeslagen.\n_Probeer 'm met `/ai test`._", ephemeral=True
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Persona form failed")
        message = f"⚠️ Opslaan mislukt: {type(error).__name__}: {error}"[:400]
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AICog(bot))
