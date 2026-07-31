import logging
import pkgutil
import time
from collections import defaultdict, deque

import discord
from discord import app_commands
from discord.ext import commands

from core.config import Settings

log = logging.getLogger(__name__)

# Per user, across every slash command. Generous enough that normal use never
# notices, tight enough that nobody can hammer /leaderboard in a loop.
RATE_LIMIT_USES = 5
RATE_LIMIT_SECONDS = 15.0


class RateLimitedTree(app_commands.CommandTree):
    """Applies one shared cooldown to every slash command.

    Done here rather than with a decorator per command so a new cog cannot
    forget it, and so the limit lives in one place.
    """

    def __init__(self, client: discord.Client) -> None:
        super().__init__(client)
        self._uses: dict[int, deque[float]] = defaultdict(deque)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Autocomplete fires on every keystroke and must never be throttled.
        if interaction.type is not discord.InteractionType.application_command:
            return True

        now = time.monotonic()
        recent = self._uses[interaction.user.id]
        while recent and now - recent[0] > RATE_LIMIT_SECONDS:
            recent.popleft()

        if len(recent) >= RATE_LIMIT_USES:
            wait = RATE_LIMIT_SECONDS - (now - recent[0])
            await interaction.response.send_message(
                f"🐢 Rustig aan — probeer het over **{wait:.0f} seconden** nog eens.",
                ephemeral=True,
            )
            return False

        recent.append(now)
        return True

    async def on_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Say what went wrong instead of letting Discord time the interaction out.

        Without this, anything raised inside a command is logged server-side and
        the person sees only "the application did not respond" — which looks
        identical whether the bot crashed, lacks a permission, or does not have
        the command at all.
        """
        original = getattr(error, "original", error)

        if isinstance(error, app_commands.CommandNotFound):
            # Discord remembered a command from a sync the running build no
            # longer backs. Almost always a deploy that did not happen.
            text = (
                f"🚫 Dit commando kent deze bot niet. Discord onthield het van een "
                f"eerdere versie; hier draait **v{self.client.settings.version}**.\n"
                "_Waarschijnlijk moet de bot opnieuw gebouwd worden._"
            )
        elif isinstance(error, app_commands.CheckFailure):
            # The rate limiter already replied for its own refusals.
            if interaction.response.is_done():
                return
            text = "🚫 Je hebt niet de rechten om dit commando te gebruiken."
        elif isinstance(original, discord.Forbidden):
            text = (
                "🚫 De bot mist een recht dat hiervoor nodig is. Controleer zijn "
                "kanaalrechten, en bij dempen ook *Moderate Members* en de rolvolgorde."
            )
        else:
            detail = f"{type(original).__name__}: {original}"
            text = (
                f"⚠️ Er ging iets mis bij dit commando.\n```{detail[:400]}```"
                "_De volledige fout staat in de logs van de bot._"
            )

        log.exception(
            "Command %s failed for %s",
            getattr(interaction.command, "qualified_name", "?"),
            interaction.user,
            exc_info=error,
        )

        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except discord.HTTPException:
            log.warning("Could not report the error back to the user")


class SpellBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True  # populate member cache so leaderboard resolves names
        super().__init__(command_prefix=settings.prefix, intents=intents, tree_cls=RateLimitedTree)

        self.settings = settings
        self.started_at = discord.utils.utcnow()

        from repositories.sqlite_repo import SqliteScoreRepository

        self.repo = SqliteScoreRepository(settings.db_path)

    async def setup_hook(self) -> None:
        await self._load_cogs()
        await self._sync_commands()

    async def _load_cogs(self) -> None:
        """Load every cog, isolating failures so one broken cog can't kill the bot."""
        import cogs

        loaded: list[str] = []
        failed: list[str] = []

        for mod in pkgutil.iter_modules(cogs.__path__):
            try:
                await self.load_extension(f"cogs.{mod.name}")
                loaded.append(mod.name)
            except Exception:
                failed.append(mod.name)
                log.exception("Cog '%s' failed to load — continuing without it", mod.name)

        log.info("Cogs loaded (%d): %s", len(loaded), ", ".join(loaded) or "none")
        if failed:
            log.warning(
                "Cogs FAILED (%d): %s — their commands will be missing in Discord",
                len(failed),
                ", ".join(failed),
            )

    async def _sync_commands(self) -> None:
        """Register slash commands. A failure here is logged, never fatal.

        A guild sync (DEV_GUILD_ID) shows up in Discord immediately; the global
        sync can take up to an hour to propagate, which makes new commands look
        broken when they are merely not there yet.
        """
        guild_id = self.settings.dev_guild_id
        try:
            if guild_id is not None:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info("Synced %d command(s) to guild %s (instant)", len(synced), guild_id)
            else:
                synced = await self.tree.sync()
                log.info(
                    "Synced %d command(s) globally — can take up to an hour to appear",
                    len(synced),
                )
            for cmd in sorted(c.name for c in synced):
                log.info("  /%s", cmd)
        except Exception:
            # Deliberately broad: sync raises from several unrelated hierarchies
            # (HTTPException, but also AppCommandError subclasses like
            # CommandLimitReached and TranslationError). A failed sync must leave
            # the bot running — on_message still works without slash commands.
            log.exception(
                "Slash-command sync FAILED — Discord keeps the previously synced set, "
                "so new commands will be missing and removed ones will linger"
            )

    async def on_ready(self) -> None:
        log.info(
            "Logged in as %s (v%s) in %d guild(s)",
            self.user,
            self.settings.version,
            len(self.guilds),
        )
