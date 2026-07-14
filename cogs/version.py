"""Version cog: report running version and compare against GitHub."""

import aiohttp
import discord
from discord.ext import commands

RAW_URL = "https://raw.githubusercontent.com/{repo}/{branch}/VERSION"


class VersionCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

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

    @commands.hybrid_command(name="version", description="Show running version and check GitHub for updates")
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VersionCog(bot))
