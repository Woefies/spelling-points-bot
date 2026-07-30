"""Reminders cog: scheduled channel reminders.

Frequencies: daily / weekdays (Mon-Fri) / weekly / monthly / once.
A reminder holds one *or more* times of day, stored comma-separated in one row.

No reminder text lives in this file: every reminder is created at runtime and
stored in the database, so changing one never needs a code change or a redeploy.

/reminder add            -> create a reminder
/reminder edit <id>      -> change text, time, channel or mention in place
/reminder list           -> overview with IDs
/reminder remove <id>    -> delete by ID
"""

import calendar
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from services.variants import pick_variant

TZ = ZoneInfo("Europe/Amsterdam")

MENTION_PREFIX = {
    "everyone": "@everyone ",
    "here": "@here ",
    "none": "",
}

WEEKDAYS_NL = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]


def _parse_times(value: str) -> str | None:
    """Parse 'HH:MM' or 'HH:MM, HH:MM, ...' into a normalised, sorted, deduped string.

    A reminder that has to fire several times a day is one row with several
    times, not several rows — one message to edit, one ID to remember.
    Returns None if any part is not a valid time.
    """
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        return None

    times = set()
    for part in parts:
        try:
            times.add(datetime.strptime(part, "%H:%M").strftime("%H:%M"))
        except ValueError:
            return None
    return ",".join(sorted(times))


def _times_of(reminder_time: str) -> list[str]:
    return [t for t in reminder_time.split(",") if t]


def _format_times(reminder_time: str) -> str:
    """'09:00,11:00,13:00' -> '09:00, 11:00 en 13:00'."""
    times = _times_of(reminder_time)
    if len(times) == 1:
        return times[0]
    return f"{', '.join(times[:-1])} en {times[-1]}"


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
            if current_time not in _times_of(rem.time):
                continue
            # last_fired records date *and* slot, so a reminder with several times
            # can fire at each of them while the 30s loop still can't double-send
            # within one minute. Older rows hold a bare date, which simply never
            # matches — costing one extra send on the day of the upgrade.
            slot = f"{today} {current_time}"
            if rem.last_fired == slot:
                continue

            due = False
            if rem.frequency == "daily":
                due = True
            elif rem.frequency == "weekdays":
                due = now.weekday() < 5  # Mon-Fri
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
                        f"{prefix}{pick_variant(rem.message)}",
                        allowed_mentions=discord.AllowedMentions(everyone=True),
                    )
                except discord.HTTPException:
                    pass

            if rem.frequency == "once":
                self.reminders.remove(rem.guild_id, rem.id)
            else:
                self.reminders.mark_fired(rem.id, slot)

    @check_reminders.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()

    # -------------------------------------------------------------- commands

    reminder = app_commands.Group(
        name="reminder",
        description="Beheer geplande herinneringen — begin met /reminder list voor een overzicht",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @reminder.command(name="add", description="Maak een eigen herinnering, eenmalig of terugkerend op een of meer vaste tijden")
    @app_commands.describe(
        bericht="De tekst. Meerdere varianten scheiden met | dan wisselt de bot af: Lunch!|Eten!",
        tijd="Tijd als HH:MM. Meerdere momenten per dag met kommas: 09:00, 13:00, 17:00",
        frequentie="Elke dag, alleen werkdagen, wekelijks, maandelijks of eenmalig",
        weekdag="Alleen invullen bij wekelijks: op welke dag van de week",
        dag="Alleen invullen bij maandelijks: welke dag van de maand, 1 t/m 31 (bijv. 24)",
        datum="Alleen invullen bij eenmalig: de datum als DD-MM-JJJJ, bijv. 24-12-2026",
        mention="Wie er gepingd wordt bij deze herinnering. Standaard niemand",
        kanaal="In welk kanaal. Standaard het kanaal waar je dit commando typt",
    )
    @app_commands.choices(
        frequentie=[
            app_commands.Choice(name="dagelijks", value="daily"),
            app_commands.Choice(name="elke werkdag (ma-vr)", value="weekdays"),
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
        time = _parse_times(tijd)
        if time is None:
            await interaction.response.send_message(
                "🚫 Ongeldige tijd. Gebruik HH:MM, bijv. `16:00`. "
                "Meerdere momenten per dag scheid je met komma's: `09:00, 13:00`.",
                ephemeral=True,
            )
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
            # Check the earliest slot: times are stored sorted, and a one-off is
            # only pointless if even its first moment has already passed.
            earliest = _times_of(time)[0]
            if datetime.strptime(f"{date} {earliest}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ) <= datetime.now(TZ):
                await interaction.response.send_message("🚫 Dat moment ligt in het verleden.", ephemeral=True)
                return

        target = kanaal or interaction.channel
        mention_value = mention.value if mention else "none"

        reminder_id = self.reminders.add(
            interaction.guild_id, target.id, bericht, time, freq,
            day=day, date=date, mention=mention_value,
        )

        await interaction.response.send_message(
            f"✅ Herinnering **#{reminder_id}** aangemaakt: {self._describe(freq, day, date)} "
            f"om **{_format_times(time)}** "
            f"in {target.mention} — \"{bericht}\"",
            ephemeral=True,
        )

    @reminder.command(name="edit", description="Pas tekst, tijd, kanaal of mention aan zonder de herinnering opnieuw te maken")
    @app_commands.describe(
        id="Het nummer uit /reminder list, bijv. 8",
        bericht="Nieuwe tekst. Varianten scheiden met | zodat de bot afwisselt",
        tijd="Nieuwe tijd(en) als HH:MM. Meerdere per dag met komma's: 09:00, 13:00, 17:00",
        kanaal="Verplaats de herinnering naar een ander kanaal",
        mention="Wie er gepingd wordt bij deze herinnering",
    )
    @app_commands.choices(
        mention=[
            app_commands.Choice(name="@everyone", value="everyone"),
            app_commands.Choice(name="@here", value="here"),
            app_commands.Choice(name="niemand", value="none"),
        ],
    )
    async def edit_cmd(
        self,
        interaction: discord.Interaction,
        id: int,
        bericht: str | None = None,
        tijd: str | None = None,
        kanaal: discord.TextChannel | None = None,
        mention: app_commands.Choice[str] | None = None,
    ) -> None:
        existing = self.reminders.get(interaction.guild_id, id)
        if existing is None:
            await interaction.response.send_message(
                f"🚫 Geen herinnering met ID **{id}**. Bekijk ze met `/reminder list`.",
                ephemeral=True,
            )
            return

        times = None
        if tijd is not None:
            times = _parse_times(tijd)
            if times is None:
                await interaction.response.send_message(
                    "🚫 Ongeldige tijd. Gebruik HH:MM, meerdere gescheiden door komma's.",
                    ephemeral=True,
                )
                return

        if bericht is None and times is None and kanaal is None and mention is None:
            await interaction.response.send_message(
                "🚫 Vul minstens één veld in dat je wilt wijzigen.", ephemeral=True
            )
            return

        self.reminders.update(
            interaction.guild_id,
            id,
            message=bericht,
            time=times,
            channel_id=kanaal.id if kanaal else None,
            mention=mention.value if mention else None,
        )

        updated = self.reminders.get(interaction.guild_id, id)
        channel = self.bot.get_channel(updated.channel_id)
        where = channel.mention if channel else f"kanaal {updated.channel_id}"
        await interaction.response.send_message(
            f"✏️ Herinnering **#{id}** aangepast: "
            f"{self._describe(updated.frequency, updated.day, updated.date)} om "
            f"**{_format_times(updated.time)}** in {where} — \"{updated.message}\"",
            ephemeral=True,
        )

    @reminder.command(name="list", description="Toon alle herinneringen met hun ID, tijden en kanaal")
    async def list_cmd(self, interaction: discord.Interaction) -> None:
        rows = self.reminders.list_for_guild(interaction.guild_id)
        if not rows:
            await interaction.response.send_message("Er zijn nog geen herinneringen. Gebruik `/reminder add` om er een te maken.", ephemeral=True)
            return

        embed = discord.Embed(title="⏰ Herinneringen", color=discord.Color.blurple())
        lines = []
        for rem in rows:
            channel = self.bot.get_channel(rem.channel_id)
            channel_name = channel.mention if channel else f"kanaal {rem.channel_id}"
            ping = f" ({MENTION_PREFIX[rem.mention].strip()})" if rem.mention != "none" else ""
            lines.append(
                f"**#{rem.id}** — {self._describe(rem.frequency, rem.day, rem.date)} "
                f"om **{_format_times(rem.time)}** "
                f"in {channel_name}{ping}\n> {rem.message}"
            )
        embed.description = "\n\n".join(lines)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reminder.command(name="remove", description="Verwijder een herinnering aan de hand van het ID uit /reminder list")
    @app_commands.describe(id="Het nummer uit /reminder list, bijv. 8")
    async def remove_cmd(self, interaction: discord.Interaction, id: int) -> None:
        if self.reminders.remove(interaction.guild_id, id):
            await interaction.response.send_message(f"🗑️ Herinnering **#{id}** verwijderd.", ephemeral=True)
        else:
            await interaction.response.send_message(f"🚫 Geen herinnering gevonden met ID **{id}**.", ephemeral=True)

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _describe(frequency: str, day: int | None, date: str | None) -> str:
        if frequency == "daily":
            return "dagelijks"
        if frequency == "weekdays":
            return "elke werkdag"
        if frequency == "weekly":
            return f"wekelijks op {WEEKDAYS_NL[day]}" if day is not None else "wekelijks"
        if frequency == "monthly":
            return f"maandelijks op de {day}e" if day is not None else "maandelijks"
        if frequency == "once" and date:
            return f"eenmalig op {datetime.strptime(date, '%Y-%m-%d').strftime('%d-%m-%Y')}"
        return frequency


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RemindersCog(bot))
