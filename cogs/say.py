"""Say cog: post a message as the bot.

The invoker's input never appears in the channel — the confirmation back to them
is ephemeral, and the message itself is a plain bot message with no attribution.
Gated behind Manage Server: an unrestricted version lets anyone put words in the
bot's mouth.
"""

import discord
from discord import app_commands
from discord.ext import commands

MAX_LENGTH = 2000  # Discord's per-message limit


class SayCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="say", description="Laat de bot een bericht plaatsen. Niemand ziet dat jij het was")
    @app_commands.describe(
        message="Wat de bot zegt. \\n = nieuwe regel, \\n\\n = witregel. Maximaal 2000 tekens",
        channel="Waar het bericht komt. Standaard het kanaal waar je dit commando typt",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def say(
        self,
        interaction: discord.Interaction,
        message: str,
        channel: discord.TextChannel | None = None,
    ) -> None:
        # Slash-command input is single-line, so let the user type \n for breaks.
        text = message.replace("\\n", "\n")
        if len(text) > MAX_LENGTH:
            await interaction.response.send_message(
                f"🚫 Te lang: {len(text)} tekens, Discord staat er {MAX_LENGTH} toe.",
                ephemeral=True,
            )
            return

        target = channel or interaction.channel
        if target is None:
            await interaction.response.send_message(
                "🚫 Kon het doelkanaal niet bepalen.", ephemeral=True
            )
            return

        if not target.permissions_for(interaction.guild.me).send_messages:
            await interaction.response.send_message(
                f"🚫 Ik heb geen rechten om te posten in {target.mention}.", ephemeral=True
            )
            return

        try:
            # Mentions are stripped: without this, anyone with Manage Server could
            # mass-ping through the bot while staying anonymous.
            sent = await target.send(text, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            await interaction.response.send_message(
                f"🚫 Versturen mislukt: {exc}", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ Geplaatst in {target.mention} — {sent.jump_url}", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SayCog(bot))
