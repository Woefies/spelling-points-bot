import logging
import pkgutil

import discord
from discord.ext import commands

from core.config import Settings

log = logging.getLogger(__name__)


class SpellBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True  # populate member cache so leaderboard resolves names
        super().__init__(command_prefix=settings.prefix, intents=intents)

        self.settings = settings

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
