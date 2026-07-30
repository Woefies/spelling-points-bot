"""Score-reporting cog: score lookup, leaderboards, and admin corrections."""

import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
PERIODS = {"week": 7, "maand": 30}


class ScoresCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="score", description="Toon hoeveel strafpunten iemand heeft verzameld. Standaard jezelf")
    @app_commands.describe(member="Van wie je de stand wilt zien. Leeg laten voor je eigen punten")
    async def score(self, ctx: commands.Context, member: discord.Member = None) -> None:
        if ctx.guild is None:
            await ctx.reply("Dit werkt alleen in een server.")
            return

        member = member or ctx.author
        pts = self.bot.repo.get_score(ctx.guild.id, member.id)
        await ctx.reply(f"📊 **{member.display_name}** heeft **{pts}** strafpunt(en).", mention_author=False)

    @commands.hybrid_command(name="leaderboard", description="De ranglijst van de meeste spelfouten")
    @app_commands.describe(period="Over welke periode. Standaard aller tijden")
    @app_commands.choices(
        period=[
            app_commands.Choice(name="deze week", value="week"),
            app_commands.Choice(name="deze maand", value="maand"),
            app_commands.Choice(name="aller tijden", value="alles"),
        ]
    )
    async def leaderboard(self, ctx: commands.Context, period: str = "alles") -> None:
        if ctx.guild is None:
            await ctx.reply("Dit werkt alleen in een server.")
            return

        if period in PERIODS:
            # scores holds running totals only, so any window has to come from
            # the timestamped log.
            now = datetime.now(timezone.utc)
            fmt = "%Y-%m-%d %H:%M:%S"
            rows = self.bot.repo.leaderboard_between(
                ctx.guild.id,
                (now - timedelta(days=PERIODS[period])).strftime(fmt),
                now.strftime(fmt),
                10,
            )
            title = f"🏆 Meeste fouten — {'afgelopen week' if period == 'week' else 'afgelopen maand'}"
        else:
            rows = self.bot.repo.leaderboard(ctx.guild.id, 10)
            title = "🏆 Meeste fouten — aller tijden"
        if not rows:
            await ctx.reply("Nog geen fouten in deze periode. 🎉", mention_author=False)
            return

        embed = discord.Embed(title=title, color=discord.Color.red())
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
            medal = MEDALS.get(rank, f"{rank}.")
            lines.append(f"{medal} **{name}** — {m}")
        embed.description = "\n".join(lines)
        await ctx.reply(embed=embed, mention_author=False)


    points = app_commands.Group(
        name="points",
        description="Puntenstanden corrigeren",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @points.command(name="adjust", description="Tel punten op of trek ze af bij iemand")
    @app_commands.describe(
        member="Wiens stand je aanpast",
        amount="Aantal punten. Negatief om af te trekken, bijv. -3",
        reason="Waarom. Komt in de logs te staan",
    )
    async def adjust_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: app_commands.Range[int, -10000, 10000],
        reason: str | None = None,
    ) -> None:
        if amount == 0:
            await interaction.response.send_message("🚫 Nul verandert niets.", ephemeral=True)
            return

        total = self.bot.repo.adjust_points(interaction.guild_id, member.id, amount)
        log.info(
            "%s adjusted %s by %+d in guild %s (%s)",
            interaction.user, member, amount, interaction.guild_id, reason or "no reason given",
        )
        note = "\n_De stand kan niet onder nul._" if total == 0 and amount < 0 else ""
        await interaction.response.send_message(
            f"✅ **{member.display_name}**: {amount:+d} → staat nu op **{total}**.{note}",
            ephemeral=True,
        )

    @points.command(name="reset", description="Zet de puntenstand van iemand terug op nul")
    @app_commands.describe(member="Wiens stand je op nul zet")
    async def reset_cmd(self, interaction: discord.Interaction, member: discord.Member) -> None:
        current = self.bot.repo.get_score(interaction.guild_id, member.id)
        if not current:
            await interaction.response.send_message(
                f"ℹ️ **{member.display_name}** staat al op nul.", ephemeral=True
            )
            return

        self.bot.repo.adjust_points(interaction.guild_id, member.id, -current)
        log.info("%s reset %s in guild %s", interaction.user, member, interaction.guild_id)
        await interaction.response.send_message(
            f"🧹 **{member.display_name}** stond op {current} en staat nu op **0**.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ScoresCog(bot))
