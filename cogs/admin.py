"""Admin cog: manage per-guild spelling-checker whitelist."""

import discord
from discord.ext import commands


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="whitelist", description="Manage ignored words")
    @commands.has_permissions(manage_guild=True)
    async def whitelist(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.reply("Use `whitelist add <word>` or `whitelist remove <word>`.")

    @whitelist.command(name="add", description="Add a word to the whitelist")
    async def whitelist_add(self, ctx: commands.Context, word: str) -> None:
        self.bot.repo.add_whitelist(ctx.guild.id, word.lower())
        await ctx.reply(f"✅ `{word.lower()}` added to whitelist.")

    @whitelist.command(name="remove", description="Remove a word from the whitelist")
    async def whitelist_remove(self, ctx: commands.Context, word: str) -> None:
        self.bot.repo.remove_whitelist(ctx.guild.id, word.lower())
        await ctx.reply(f"🗑️ `{word.lower()}` removed from whitelist.")

    @whitelist.error
    async def whitelist_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("🚫 You need `Manage Server` permission to do that.")
        else:
            raise error


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
