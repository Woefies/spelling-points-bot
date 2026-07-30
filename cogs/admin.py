"""Admin cog: manage per-guild spelling-checker whitelist."""

import discord
from discord import app_commands
from discord.ext import commands

from services.lexicon import CHAT_SLANG


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

    @whitelist.command(name="list", description="Toon welke woorden de bot in deze server goedkeurt")
    async def whitelist_list(self, ctx: commands.Context) -> None:
        words = sorted(self.bot.repo.get_whitelist(ctx.guild.id))
        builtin = len(self.bot.settings.whitelist) + len(CHAT_SLANG)

        if not words:
            await ctx.reply(
                f"Deze server heeft nog geen eigen woorden op de whitelist.\n"
                f"Er zijn er wel **{builtin}** ingebouwd (chattaal zoals `idk` en `gwn`).\n"
                f"Toevoegen kan met `/whitelist add <woord>`.",
                ephemeral=True,
            )
            return

        # A long whitelist would blow past Discord's 2000-character message limit.
        shown, total = words, len(words)
        text = ", ".join(f"`{w}`" for w in shown)
        while len(text) > 1600 and shown:
            shown = shown[:-25]
            text = ", ".join(f"`{w}`" for w in shown)

        tail = f"\n\n_… en nog {total - len(shown)} meer._" if len(shown) < total else ""
        await ctx.reply(
            f"📗 **{total}** eigen woord(en) op de whitelist, plus **{builtin}** ingebouwd:\n"
            f"{text}{tail}",
            ephemeral=True,
        )

    @whitelist.error
    async def whitelist_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("🚫 Hiervoor heb je het recht `Manage Server` nodig.", ephemeral=True)
        else:
            raise error


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
