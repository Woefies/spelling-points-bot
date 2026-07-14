import pkgutil

import discord
from discord.ext import commands

from core.config import Settings


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
        import cogs

        for mod in pkgutil.iter_modules(cogs.__path__):
            await self.load_extension(f"cogs.{mod.name}")

        await self.tree.sync()

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user}")
