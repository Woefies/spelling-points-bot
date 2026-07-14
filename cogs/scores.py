"""Score-reporting cog: user score lookup and guild leaderboard."""

import discord
from discord.ext import commands


class ScoresCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="score", description="Show a user's spelling-mistake tally")
    async def score(self, ctx: commands.Context, member: discord.Member = None) -> None:
        if ctx.guild is None:
            await ctx.reply("Guild only.")
            return

        member = member or ctx.author
        pts = self.bot.repo.get_score(ctx.guild.id, member.id)
        await ctx.reply(f"📊 {member.display_name} has **{pts}** mistake point(s).", mention_author=False)

    @commands.hybrid_command(name="leaderboard", description="Top spelling offenders")
    async def leaderboard(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.reply("Guild only.")
            return

        rows = self.bot.repo.leaderboard(ctx.guild.id, 10)
        if not rows:
            await ctx.reply("No mistakes recorded yet. 🎉")
            return

        embed = discord.Embed(title="🏆 Spelling Mistake Leaderboard", color=discord.Color.red())
        lines = []
        for rank, (uid, m) in enumerate(rows, start=1):
            member = ctx.guild.get_member(uid)
            if member is None:
                user = self.bot.get_user(uid)
                if user is None:
                    try:
                        user = await self.bot.fetch_user(uid)
                    except discord.HTTPException:
                        user = None
                name = user.name if user else f"User {uid}"
            else:
                name = member.display_name
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")
            lines.append(f"{medal} **{name}** — {m}")
        embed.description = "\n".join(lines)
        await ctx.reply(embed=embed, mention_author=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ScoresCog(bot))
