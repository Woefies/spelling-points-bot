"""Version cog: report the running version, and watch GitHub for newer ones.

The watcher exists because "there is a new version" was information nobody had
unless they thought to ask. It only tells you; deploying is scripts/auto_update.sh
or a person.
"""

import datetime
import logging
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

log = logging.getLogger(__name__)

RAW_URL = "https://raw.githubusercontent.com/{repo}/{branch}/VERSION"

CONFIG_CHANNEL = "update_channel"
CONFIG_ANNOUNCED = "update_announced"  # last version we already mentioned
REQUEST_FILE = ".update-requested"  # picked up by scripts/auto_update.sh
RESULT_FILE = ".update-result"  # written by that script, read once on the next start
CONFIG_SEEN = "update_last_seen"  # detects a rebuild nobody announced
# Fixed offset rather than ZoneInfo, matching cogs/backup.py: an hour of drift in
# summer is irrelevant for a daily check.
CHECK_AT = datetime.time(hour=9, minute=0, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))


class VersionCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.check_updates.start()

    def cog_unload(self) -> None:
        self.check_updates.cancel()

    @tasks.loop(time=CHECK_AT)
    async def check_updates(self) -> None:
        latest = await self._fetch_latest()
        running = self.bot.settings.version
        if latest is None or latest == running:
            return

        for guild_id, channel_id in self.bot.repo.all_config(CONFIG_CHANNEL):
            # Say it once per version, not every morning until someone acts.
            if self.bot.repo.get_config(guild_id, CONFIG_ANNOUNCED) == latest:
                continue
            channel = self.bot.get_channel(int(channel_id))
            if channel is None:
                log.warning("Update channel %s for guild %s not found", channel_id, guild_id)
                continue
            try:
                await channel.send(
                    f"⬆️ Er staat een nieuwe versie klaar: **v{latest}** "
                    f"(deze bot draait **v{running}**)."
                )
            except discord.HTTPException:
                log.exception("Could not announce update in %s", channel_id)
                continue
            self.bot.repo.set_config(guild_id, CONFIG_ANNOUNCED, latest)

    @check_updates.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()
        await self._report_restart()

    async def _report_restart(self) -> None:
        """Say what happened, once, on the first start after a rebuild.

        The bot cannot watch its own replacement, so the outcome arrives two ways:
        a result file from the update script, or — for a rebuild someone did by
        hand — the running version simply differing from what was last seen.
        """
        path = Path(self.bot.settings.db_path).parent / RESULT_FILE
        outcome = None
        if path.exists():
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
                outcome = (lines + ["", "", "", ""])[:4]
            except OSError:
                log.warning("Could not read %s", path)
            finally:
                path.unlink(missing_ok=True)

        running = self.bot.settings.version
        for guild_id, channel_id in self.bot.repo.all_config(CONFIG_CHANNEL):
            seen = self.bot.repo.get_config(guild_id, CONFIG_SEEN)
            self.bot.repo.set_config(guild_id, CONFIG_SEEN, running)

            if outcome and outcome[0] == "failed":
                text = (
                    f"❌ Update naar **v{outcome[2]}** mislukt — {outcome[3] or 'onbekende reden'}\n"
                    f"Er is teruggerold; ik draai nog op **v{running}**."
                )
            elif outcome and outcome[0] == "ok":
                text = f"✅ Bijgewerkt van **v{outcome[1]}** naar **v{running}**."
            elif seen and seen != running:
                # No result file: someone rebuilt by hand rather than via the script.
                text = f"✅ Ik draai nu op **v{running}** (was **v{seen}**)."
            else:
                continue

            channel = self.bot.get_channel(int(channel_id))
            if channel is None:
                continue
            try:
                await channel.send(text)
            except discord.HTTPException:
                log.warning("Could not report restart in %s", channel_id)

    async def _fetch_latest(self) -> str | None:
        s = self.bot.settings
        url = RAW_URL.format(repo=s.github_repo, branch=s.github_branch)
        timeout = aiohttp.ClientTimeout(total=8)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return None
                    return (await resp.text()).strip()
        except aiohttp.ClientError:
            return None

    @commands.hybrid_command(name="version", description="Toon welke versie draait en of er een nieuwere beschikbaar is")
    async def version(self, ctx: commands.Context) -> None:
        running = self.bot.settings.version
        latest = await self._fetch_latest()

        if latest is None:
            await ctx.reply(
                f"Running **v{running}**. ⚠️ Couldn't reach GitHub to check for updates.",
                mention_author=False,
            )
            return

        if running == latest:
            await ctx.reply(
                f"✅ Up to date — running **v{running}** (latest on GitHub).",
                mention_author=False,
            )
        else:
            await ctx.reply(
                f"⚠️ Update available — running **v{running}**, latest is **v{latest}**. "
                f"Pull and rebuild to update.",
                mention_author=False,
            )


    update = app_commands.Group(
        name="update",
        description="Melden wanneer er een nieuwe versie van de bot klaarstaat",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @update.command(name="enable", description="Meld het in een kanaal zodra er een nieuwe versie is")
    @app_commands.describe(channel="Waar de melding geplaatst wordt. Eén bericht per versie")
    async def enable_cmd(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        self.bot.repo.set_config(interaction.guild_id, CONFIG_CHANNEL, str(channel.id))
        await interaction.response.send_message(
            f"✅ Updatemeldingen staan aan in {channel.mention}.\n"
            "_De bot meldt het alleen — uitrollen blijft handwerk of de taakplanner._",
            ephemeral=True,
        )

    @update.command(name="now", description="Vraag een update aan. De taakplanner pakt hem op")
    async def now_cmd(self, interaction: discord.Interaction) -> None:
        # A file in the mounted data volume, not a rebuild: the bot runs inside
        # the container being replaced, and giving it the Docker socket would
        # hand host-level access to something that reacts to user messages.
        path = Path(self.bot.settings.db_path).parent / REQUEST_FILE
        latest = await self._fetch_latest()
        running = self.bot.settings.version

        if path.exists():
            # A request that just sits there almost always means the scheduled
            # task was never set up — say that rather than "wait for the next
            # round", which implies a round is coming.
            try:
                age = discord.utils.utcnow().timestamp() - path.stat().st_mtime
            except OSError:
                age = 0
            hours = age / 3600

            if hours < 24:
                extra = "De taakplanner pakt het op bij de volgende ronde."
            else:
                extra = (
                    f"Het staat er al **{hours / 24:.0f} dag(en)** — dat wijst erop dat de "
                    "updatetaak niet is ingesteld op de host. Dan gebeurt er niets tot "
                    "iemand `scripts/auto_update.sh` draait."
                )
            await interaction.response.send_message(
                f"ℹ️ Er staat al een verzoek klaar. {extra}", ephemeral=True
            )
            return

        try:
            path.write_text(
                f"requested by {interaction.user} at "
                f"{discord.utils.utcnow().isoformat(timespec='seconds')}\n",
                encoding="utf-8",
            )
        except OSError as exc:
            await interaction.response.send_message(
                f"🚫 Kon het verzoek niet wegschrijven: `{exc}`", ephemeral=True
            )
            return

        log.info("%s requested an update in guild %s", interaction.user, interaction.guild_id)
        note = (
            f"Er staat **v{latest}** klaar, deze draait **v{running}**."
            if latest and latest != running
            else f"Er is geen nieuwere versie — hij herbouwt op **v{running}**."
        )
        await interaction.response.send_message(
            f"📥 Verzoek genoteerd. {note}\n"
            "De bot herstart zichzelf zodra de taakplanner langskomt en meldt daarna "
            "in het ingestelde kanaal of het gelukt is.\n"
            "_Werkt alleen als `scripts/auto_update.sh` als taak is ingesteld._",
            ephemeral=True,
        )

    @update.command(name="cancel", description="Trek een openstaand updateverzoek weer in")
    async def cancel_cmd(self, interaction: discord.Interaction) -> None:
        path = Path(self.bot.settings.db_path).parent / REQUEST_FILE
        if not path.exists():
            await interaction.response.send_message(
                "ℹ️ Er stond geen verzoek open.", ephemeral=True
            )
            return
        path.unlink(missing_ok=True)
        log.info("%s cancelled the pending update request", interaction.user)
        await interaction.response.send_message("🗑️ Verzoek ingetrokken.", ephemeral=True)

    @update.command(name="disable", description="Zet de updatemeldingen uit")
    async def disable_cmd(self, interaction: discord.Interaction) -> None:
        self.bot.repo.set_config(interaction.guild_id, CONFIG_CHANNEL, None)
        self.bot.repo.set_config(interaction.guild_id, CONFIG_ANNOUNCED, None)
        await interaction.response.send_message("🛑 Updatemeldingen staan uit.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VersionCog(bot))
