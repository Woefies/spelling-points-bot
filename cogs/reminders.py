"""Reminders cog: scheduled channel reminders (daily / weekly / monthly / once).

/reminder setup #kanaal  -> seeds the default reminders:
    - daily 16:00  "@everyone ⏰ Check je uren!"
    - monthly 24th 16:00  "@everyone 💰 Het is payday!"
/reminder add            -> custom reminders
/reminder list           -> overview with IDs
/reminder remove <id>    -> delete by ID
"""

import calendar
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

TZ = ZoneInfo("Europe/Amsterdam")

DEFAULT_HOURS_MESSAGE = "⏰ Check je uren!"
DEFAULT_PAYDAY_MESSAGE = "💰 Het is payday!"

MENTION_PREFIX = {
    "everyone": "@everyone ",
    "here": "@here ",
    "none": "",
}

WEEKDAYS_NL = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]


def _parse_time(value: str) -> str | None:
    """Validate and normalise 'H:MM' / 'HH:MM' -> 'HH:MM'; None if invalid."""
    try:
        parsed = datetime.strptime(value.strip(), "%H:%M")
    except ValueError:
        return None
    return parsed.strftime("%H:%M")


def _parse_date(value: str) -> str | None:
    """Accept DD-MM-YYYY or YYYY-MM-DD; return ISO 'YYYY-MM-DD' or None."""
    value = value.strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _effective_monthly_day(target_day: int, year: int, month: int) -> int:
    """Clamp e.g. day 31 to the last day of shorter months."""
    return min(target_day, calendar.monthrange(year, month)[1])


class RemindersCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        from repositories.reminders_repo import SqliteReminderRepository

        self.reminders = SqliteReminderRepository(bot.settings.db_path)
        self.check_reminders.start()

    def cog_unload(self) -> None:
        self.check_reminders.cancel()

    # ------------------------------------------------------------------ loop

    @tasks.loop(seconds=30)
    async def check_reminders(self) -> None:
        now = datetime.now(TZ)
        today = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M")

        for rem in self.reminders.all():
            if rem.time != current_time or rem.last_fired == today:
                continue

            due = False
            if rem.frequency == "daily":
                due = True
            elif rem.frequency == "weekly":
                due = rem.day == now.weekday()
            elif rem.frequency == "monthly":
                due = now.day == _effective_monthly_day(rem.day or 1, now.year, now.month)
            elif rem.frequency == "once":
                due = rem.date == today

            if not due:
                continue

            channel = self.bot.get_channel(rem.channel_id)
            if channel is not None:
                prefix = MENTION_PREFIX.get(rem.mention, "")
                try:
                    await channel.send(
                        f"{prefix}{rem.message}",
                        allowed_mentions=discord.AllowedMentions(everyone=True),
                    )
                except discord.HTTPException:
                    pass

            if rem.frequency == "once":
                self.reminders.remove(rem.guild_id, rem.id)
            else:
                self.reminders.mark_fired(rem.id, today)

    @check_reminders.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()

    # -------------------------------------------------------------- commands

    reminder = app_commands.Group(
        name="reminder",
        description="Beheer geplande herinneringen",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @reminder.command(name="setup", description="Stel het kanaal in en maak de standaard-reminders aan (uren + payday)")
    @app_commands.describe(kanaal="Kanaal waar de standaard-reminders gestuurd worden")
    async def setup_cmd(self, interaction: discord.Interaction, kanaal: discord.TextChannel) -> None:
        created = []

        if not self.reminders.exists_similar(interaction.guild_id, DEFAULT_HOURS_MESSAGE, "16:00", "daily"):
            self.reminders.add(
                interaction.guild_id, kanaal.id, DEFAULT_HOURS_MESSAGE,
                "16:00", "daily", mention="everyone",
            )
            created.append("dagelijks 16:00 — Check je uren")

        if not self.reminders.exists_similar(interaction.guild_id, DEFAULT_PAYDAY_MESSAGE, "16:00", "monthly"):
            self.reminders.add(
                interaction.guild_id, kanaal.id, DEFAULT_PAYDAY_MESSAGE,
                "16:00", "monthly", day=24, mention="everyone",
            )
            created.append("maandelijks de 24e 16:00 — Payday")

        if created:
            await interaction.response.send_message(
                f"✅ Standaard-reminders aangemaakt in {kanaal.mention}:\n" + "\n".join(f"• {c}" for c in created)
            )
        else:
            await interaction.response.send_message(
                "ℹ️ De standaard-reminders bestaan al. Gebruik `/reminder list` om ze te bekijken."
            )

    @reminder.command(name="add", description="Maak een eigen herinnering aan")
    @app_commands.describe(
        bericht="De tekst van de herinnering",
        tijd="Tijd in HH:MM (bijv. 16:00, Nederlandse tijd)",
        frequentie="Hoe vaak de herinnering herhaald wordt",
        weekdag="Alleen bij wekelijks: op welke dag",
        dag="Alleen bij maandelijks: dag van de maand (1-31)",
        datum="Alleen bij eenmalig: datum als DD-MM-YYYY",
        mention="Wie er gepinged wordt (standaard: niemand)",
        kanaal="Kanaal voor deze herinnering (standaard: dit kanaal)",
    )
    @app_commands.choices(
        frequentie=[
            app_commands.Choice(name="dagelijks", value="daily"),
            app_commands.Choice(name="wekelijks", value="weekly"),
            app_commands.Choice(name="maandelijks", value="monthly"),
            app_commands.Choice(name="eenmalig", value="once"),
        ],
        weekdag=[app_commands.Choice(name=d, value=i) for i, d in enumerate(WEEKDAYS_NL)],
        mention=[
            app_commands.Choice(name="@everyone", value="everyone"),
            app_commands.Choice(name="@here", value="here"),
            app_commands.Choice(name="niemand", value="none"),
        ],
    )
    async def add_cmd(
        self,
        interaction: discord.Interaction,
        bericht: str,
        tijd: str,
        frequentie: app_commands.Choice[str],
        weekdag: app_commands.Choice[int] | None = None,
        dag: app_commands.Range[int, 1, 31] | None = None,
        datum: str | None = None,
        mention: app_commands.Choice[str] | None = None,
        kanaal: discord.TextChannel | None = None,
    ) -> None:
        time = _parse_time(tijd)
        if time is None:
            await interaction.response.send_message("🚫 Ongeldige tijd. Gebruik HH:MM, bijv. `16:00`.", ephemeral=True)
            return

        freq = frequentie.value
        day: int | None = None
        date: str | None = None

        if freq == "weekly":
            if weekdag is None:
                await interaction.response.send_message("🚫 Kies een `weekdag` bij een wekelijkse herinnering.", ephemeral=True)
                return
            day = weekdag.value
        elif freq == "monthly":
            if dag is None:
                await interaction.response.send_message("🚫 Vul `dag` (1-31) in bij een maandelijkse herinnering.", ephemeral=True)
                return
            day = dag
        elif freq == "once":
            if datum is None:
                await interaction.response.send_message("🚫 Vul `datum` in (DD-MM-YYYY) bij een eenmalige herinnering.", ephemeral=True)
                return
            date = _parse_date(datum)
            if date is None:
                await interaction.response.send_message("🚫 Ongeldige datum. Gebruik DD-MM-YYYY, bijv. `24-12-2026`.", ephemeral=True)
                return
            if datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ) <= datetime.now(TZ):
                await interaction.response.send_message("🚫 Dat moment ligt in het verleden.", ephemeral=True)
                return

        target = kanaal or interaction.channel
        mention_value = mention.value if mention else "none"

        reminder_id = self.reminders.add(
            interaction.guild_id, target.id, bericht, time, freq,
            day=day, date=date, mention=mention_value,
        )

        await interaction.response.send_message(
            f"✅ Herinnering **#{reminder_id}** aangemaakt: {self._describe(freq, day, date)} om **{time}** "
            f"in {target.mention} — \"{bericht}\""
        )

    @reminder.command(name="list", description="Toon alle herinneringen van deze server")
    async def list_cmd(self, interaction: discord.Interaction) -> None:
        rows = self.reminders.list_for_guild(interaction.guild_id)
        if not rows:
            await interaction.response.send_message("Er zijn nog geen herinneringen. Gebruik `/reminder setup` of `/reminder add`.")
            return

        embed = discord.Embed(title="⏰ Herinneringen", color=discord.Color.blurple())
        lines = []
        for rem in rows:
            channel = self.bot.get_channel(rem.channel_id)
            channel_name = channel.mention if channel else f"kanaal {rem.channel_id}"
            ping = f" ({MENTION_PREFIX[rem.mention].strip()})" if rem.mention != "none" else ""
            lines.append(
                f"**#{rem.id}** — {self._describe(rem.frequency, rem.day, rem.date)} om **{rem.time}** "
                f"in {channel_name}{ping}\n> {rem.message}"
            )
        embed.description = "\n\n".join(lines)
        await interaction.response.send_message(embed=embed)

    @reminder.command(name="remove", description="Verwijder een herinnering op ID")
    @app_commands.describe(id="Het ID uit /reminder list")
    async def remove_cmd(self, interaction: discord.Interaction, id: int) -> None:
        if self.reminders.remove(interaction.guild_id, id):
            await interaction.response.send_message(f"🗑️ Herinnering **#{id}** verwijderd.")
        else:
            await interaction.response.send_message(f"🚫 Geen herinnering gevonden met ID **{id}**.", ephemeral=True)

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _describe(frequency: str, day: int | None, date: str | None) -> str:
        if frequency == "daily":
            return "dagelijks"
        if frequency == "weekly":
            return f"wekelijks op {WEEKDAYS_NL[day]}" if day is not None else "wekelijks"
        if frequency == "monthly":
            return f"maandelijks op de {day}e" if day is not None else "maandelijks"
        if frequency == "once" and date:
            return f"eenmalig op {datetime.strptime(date, '%Y-%m-%d').strftime('%d-%m-%Y')}"
        return frequency


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RemindersCog(bot))
