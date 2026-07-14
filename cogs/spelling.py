"""Spelling-tally cog: listens for messages, detects mistakes, and tallies points."""

import discord
from discord.ext import commands

from services.cleaner import clean
from services.detector import detect
from services.checkers import REGISTRY
from services.lexicon import CHAT_SLANG


class SpellingCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is None:
            return

        cleaned = clean(message.content)
        if not cleaned.strip():
            return

        lang = detect(cleaned, self.bot.settings.min_words_for_detect)
        if lang is None:
            return

        wl = {w.lower() for w in self.bot.settings.whitelist} | {
            w.lower() for w in self.bot.repo.get_whitelist(message.guild.id)
        } | CHAT_SLANG
        ctx = {
            "whitelist": wl,
            "skip_capitalized": self.bot.settings.skip_capitalized,
        }

        all_issues = []
        for checker in REGISTRY.values():
            result = await checker.check(cleaned, lang, ctx)
            all_issues.extend(result.issues)

        if not all_issues:
            return

        points = len(all_issues) * self.bot.settings.points_per_mistake
        self.bot.repo.add_points(message.guild.id, message.author.id, points)
        for iss in all_issues:
            self.bot.repo.log_issue(message.guild.id, message.author.id, iss.word, iss.lang, iss.kind)

        try:
            await message.add_reaction("❌")
        except discord.HTTPException:
            pass

        if self.bot.settings.reply_on_mistake:
            total = self.bot.repo.get_score(message.guild.id, message.author.id)
            words = ", ".join(f"`{i.word}`" for i in all_issues[:10])
            await message.reply(
                f"🔤 {len(all_issues)} mistake(s) [{lang}]: {words} · +{points} pts (total {total})",
                mention_author=False,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SpellingCog(bot))
