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
    DEFAULT_PERSONA,
    api_key,
    build_prompt,
    format_usage,
    generate,
    parse_usage,
)

log = logging.getLogger(__name__)

CONFIG_ENABLED = "ai_triggers"
CONFIG_PERSONA = "ai_persona"
CONFIG_BUDGET = "ai_budget"
CONFIG_USAGE = "ai_usage"
CONFIG_SEND_MESSAGE = "ai_send_message"

RESET = "-"


class AICog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------- used by triggers

    def enabled(self, guild_id: int) -> bool:
        return self.bot.repo.get_config(guild_id, CONFIG_ENABLED) == "1"

    def persona(self, guild_id: int) -> str:
        return self.bot.repo.get_config(guild_id, CONFIG_PERSONA) or DEFAULT_PERSONA

    def budget(self, guild_id: int) -> int:
        raw = self.bot.repo.get_config(guild_id, CONFIG_BUDGET)
        try:
            return int(raw) if raw else DEFAULT_BUDGET
        except ValueError:
            return DEFAULT_BUDGET

    def used_today(self, guild_id: int) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return parse_usage(self.bot.repo.get_config(guild_id, CONFIG_USAGE), today)

    def _spend(self, guild_id: int) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        used = self.used_today(guild_id)
        self.bot.repo.set_config(guild_id, CONFIG_USAGE, format_usage(today, used + 1))

    async def reply_for(self, guild_id: int, pattern: str, count: int, content: str) -> str | None:
        """A generated reply, or None so the caller uses its own stored text."""
        if not self.enabled(guild_id) or not api_key():
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
        )

    # -------------------------------------------------------------------- commands

    ai = app_commands.Group(
        name="ai",
        description="Laat de bot trigger-antwoorden zelf schrijven",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @ai.command(name="enable", description="Laat trigger-antwoorden door AI schrijven")
    async def enable_cmd(self, interaction: discord.Interaction) -> None:
        if not api_key():
            await interaction.response.send_message(
                "🚫 Er staat geen `ANTHROPIC_API_KEY` in de `.env` op de host. "
                "Zonder sleutel kan de bot niets genereren.",
                ephemeral=True,
            )
            return
        self.bot.repo.set_config(interaction.guild_id, CONFIG_ENABLED, "1")
        await interaction.response.send_message(
            f"✅ AI-antwoorden aan, maximaal **{self.budget(interaction.guild_id)}** per dag.\n"
            "_Lukt het niet, dan valt de bot terug op de vaste tekst van de trigger._",
            ephemeral=True,
        )

    @ai.command(name="disable", description="Zet AI-antwoorden uit, terug naar de vaste teksten")
    async def disable_cmd(self, interaction: discord.Interaction) -> None:
        self.bot.repo.set_config(interaction.guild_id, CONFIG_ENABLED, None)
        await interaction.response.send_message("🛑 AI-antwoorden uit.", ephemeral=True)

    @ai.command(name="persona", description="Beschrijf hoe de bot moet klinken")
    @app_commands.describe(text="Hoe de bot schrijft. Typ een - om de standaard terug te zetten")
    async def persona_cmd(self, interaction: discord.Interaction, text: str) -> None:
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

    @ai.command(name="budget", description="Maximaal aantal AI-antwoorden per dag")
    @app_commands.describe(amount="Op = terugval naar de vaste teksten. Standaard 50")
    async def budget_cmd(
        self, interaction: discord.Interaction, amount: app_commands.Range[int, 0, 1000]
    ) -> None:
        self.bot.repo.set_config(interaction.guild_id, CONFIG_BUDGET, str(amount))
        await interaction.response.send_message(
            f"✅ Dagbudget staat op **{amount}** antwoorden.", ephemeral=True
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
            await interaction.response.send_message(
                "🚫 Geen `ANTHROPIC_API_KEY` op de host.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        # Deliberately bypasses the enabled check so the persona can be tuned
        # before switching it on for the channel. It does spend budget.
        self._spend(interaction.guild_id)
        text = await generate(
            self.persona(interaction.guild_id), build_prompt(word, 3, None)
        )
        await interaction.followup.send(
            f"🤖 {text}" if text else
            "🚫 Geen antwoord gekregen. Sleutel geldig? Budget op? Kijk in de logs.",
            ephemeral=True,
        )

    @ai.command(name="status", description="Toon of AI aanstaat, het verbruik en de persona")
    async def status_cmd(self, interaction: discord.Interaction) -> None:
        gid = interaction.guild_id
        key = "aanwezig" if api_key() else "**ontbreekt op de host**"
        content = "bericht wordt meegestuurd" if self.bot.repo.get_config(gid, CONFIG_SEND_MESSAGE) == "1" \
            else "alleen het trefwoord"
        await interaction.response.send_message(
            f"🤖 AI-antwoorden: **{'aan' if self.enabled(gid) else 'uit'}** · "
            f"API-sleutel {key}\n"
            f"Vandaag gebruikt: **{self.used_today(gid)}** van **{self.budget(gid)}**\n"
            f"Context: {content}\n\n"
            f"**Persona:**\n>>> {self.persona(gid)[:1500]}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AICog(bot))
