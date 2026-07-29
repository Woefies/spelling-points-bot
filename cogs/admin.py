"""Admin cog: manage per-guild spelling-checker whitelist."""

import discord
from discord import app_commands
from discord.ext import commands


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="whitelist", description="Beheer woorden die de bot nooit als spelfout mag rekenen")
    @commands.has_permissions(manage_guild=True)
    async def whitelist(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.reply("Gebruik `/whitelist add <woord>` of `/whitelist remove <woord>`.", ephemeral=True)

    @whitelist.command(name="add", description="Voeg een woord toe zodat de bot het voortaan goedkeurt")
    @app_commands.describe(word="Het woord dat de bot voortaan moet goedkeuren, bijv. zonnebrandcreme")
    async def whitelist_add(self, ctx: commands.Context, word: str) -> None:
        self.bot.repo.add_whitelist(ctx.guild.id, word.lower())
        await ctx.reply(f"✅ `{word.lower()}` staat nu op de whitelist.", ephemeral=True)

    @whitelist.command(name="remove", description="Haal een woord van de whitelist zodat het weer als fout telt")
    @app_commands.describe(word="Het woord dat weer als spelfout mag tellen")
    async def whitelist_remove(self, ctx: commands.Context, word: str) -> None:
        self.bot.repo.remove_whitelist(ctx.guild.id, word.lower())
        await ctx.reply(f"🗑️ `{word.lower()}` telt weer mee als spelfout.", ephemeral=True)

    @whitelist.error
    async def whitelist_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("🚫 Hiervoor heb je het recht `Manage Server` nodig.", ephemeral=True)
        else:
            raise error


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
