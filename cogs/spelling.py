"""Spelling-tally cog: listens for messages, detects mistakes, and tallies points."""

import logging

import discord
from discord.ext import commands

from services.cleaner import clean
from services.detector import detect
from services.checkers import REGISTRY
from services.guild_settings import resolve
from services.lexicon import SKIP_WORDS
from services.testmode import MARKER, MUTED, TEST, state_for

log = logging.getLogger(__name__)


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

        # One read per message, merged over the .env defaults — a server can dial
        # the checker down without anyone touching the host.
        stored = self.bot.repo.config_for(message.guild.id)
        conf = resolve(stored, self.bot.settings)

        where = state_for(stored, message.channel)
        if where == MUTED:
            return

        lang = detect(cleaned, conf["min_words_for_detect"])
        if lang is None:
            return

        wl = {w.lower() for w in self.bot.settings.whitelist} | {
            w.lower() for w in self.bot.repo.get_whitelist(message.guild.id)
        } | SKIP_WORDS
        ctx = {
            "whitelist": wl,
            "skip_capitalized": conf["skip_capitalized"],
            "hunspell_dir": self.bot.settings.hunspell_dir,
        }

        all_issues = []
        for checker in REGISTRY.values():
            result = await checker.check(cleaned, lang, ctx)
            all_issues.extend(result.issues)

        if not all_issues:
            return

        points = len(all_issues) * conf["points_per_mistake"]
        words = ", ".join(f"`{i.word}`" for i in all_issues[:10])

        if where == TEST:
            # Show the full result and store none of it. The reply goes out even
            # when reply_on_mistake is off, because seeing what was flagged is
            # the entire reason the sandbox exists.
            try:
                await message.add_reaction("❌")
            except discord.HTTPException:
                pass
            try:
                await message.reply(
                    f"🔤 {len(all_issues)} fout(en) [{lang}]: {words} · "
                    f"zou +{points} punt(en) zijn\n{MARKER}",
                    mention_author=False,
                )
            except discord.HTTPException:
                log.warning("Could not reply in test channel %s", message.channel.id)
            return

        self.bot.repo.add_points(message.guild.id, message.author.id, points)
        for iss in all_issues:
            self.bot.repo.log_issue(message.guild.id, message.author.id, iss.word, iss.lang, iss.kind)

        # Decoupled on purpose: the punishment cog listens for this rather than
        # the spelling flow knowing anything about timeouts.
        self.bot.dispatch("mistakes_recorded", message, points)

        try:
            await message.add_reaction("❌")
        except discord.HTTPException:
            pass

        if conf["reply_on_mistake"]:
            total = self.bot.repo.get_score(message.guild.id, message.author.id)
            await message.reply(
                f"🔤 {len(all_issues)} mistake(s) [{lang}]: {words} · +{points} pts (total {total})",
                mention_author=False,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SpellingCog(bot))
