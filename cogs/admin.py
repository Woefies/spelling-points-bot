"""Admin cog: manage per-guild spelling-checker whitelist."""

import discord
from discord import app_commands
from discord.ext import commands

from services.lexicon import CHAT_SLANG


def _split_words(raw: str) -> list[str]:
    """Accept 'woord' or 'een, twee, drie' -> lowercased, deduped, order kept."""
    seen = {}
    for part in raw.replace("\n", ",").split(","):
        w = part.strip().lower()
        if w:
            seen[w] = None
    return list(seen)


def _join(words: list[str], limit: int = 30) -> str:
    shown = ", ".join(f"`{w}`" for w in words[:limit])
    return shown + (f" _(+{len(words) - limit} meer)_" if len(words) > limit else "")


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="whitelist", description="Beheer woorden die de bot nooit als spelfout mag rekenen")
    @commands.has_permissions(manage_guild=True)
    async def whitelist(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.reply("Gebruik `/whitelist add <woord>` of `/whitelist remove <woord>`.", ephemeral=True)

    @whitelist.command(name="add", description="Keur een of meer woorden goed zodat de bot ze niet meer fout rekent")
    @app_commands.describe(word="Woord(en) om goed te keuren. Meerdere tegelijk met kommas: dev, multisite")
    async def whitelist_add(self, ctx: commands.Context, *, word: str) -> None:
        # Comma-separated so a batch from the flagged-words report can go in at
        # once; one command per word is not workable for a list of any length.
        words = _split_words(word)
        if not words:
            await ctx.reply("🚫 Geen woord opgegeven.", ephemeral=True)
            return

        existing = self.bot.repo.get_whitelist(ctx.guild.id)
        added = [w for w in words if w not in existing]
        for w in added:
            self.bot.repo.add_whitelist(ctx.guild.id, w)

        skipped = len(words) - len(added)
        if not added:
            await ctx.reply(
                f"ℹ️ Stond er al op: {_join(words)}", ephemeral=True
            )
            return

        tail = f"\n_{skipped} stond(en) er al op._" if skipped else ""
        await ctx.reply(
            f"✅ {len(added)} woord(en) toegevoegd: {_join(added)}{tail}", ephemeral=True
        )

    @whitelist.command(name="remove", description="Haal woorden van de whitelist zodat ze weer als fout tellen")
    @app_commands.describe(word="Kies uit de lijst, of typ meerdere gescheiden door kommas")
    async def whitelist_remove(self, ctx: commands.Context, *, word: str) -> None:
        words = _split_words(word)
        existing = self.bot.repo.get_whitelist(ctx.guild.id)
        removed = [w for w in words if w in existing]
        for w in removed:
            self.bot.repo.remove_whitelist(ctx.guild.id, w)

        if not removed:
            await ctx.reply(
                f"🚫 Stond niet op de whitelist: {_join(words)}", ephemeral=True
            )
            return
        await ctx.reply(
            f"🗑️ {len(removed)} woord(en) verwijderd: {_join(removed)}", ephemeral=True
        )

    @whitelist_remove.autocomplete("word")
    async def _whitelist_choices(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        term = current.lower().rsplit(",", 1)[-1].strip()
        words = sorted(self.bot.repo.get_whitelist(interaction.guild_id))
        matches = [w for w in words if term in w] if term else words
        return [app_commands.Choice(name=w, value=w) for w in matches[:25]]

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
