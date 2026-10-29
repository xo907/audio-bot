"""
Settings Cog module.
Controls SponsorBlock filtering configuration, voice disconnection, latency checks, and help menu.
"""

import logging
from typing import Optional, Literal
import discord
from discord import app_commands
from discord.ext import commands

from bot.config import VALID_SPONSOR_CATEGORIES
from bot.ui import create_help_view, notice, error_notice, MUTED

logger = logging.getLogger("AudioBot.SettingsCog")


class SettingsCog(commands.Cog, name="Settings"):
    """Configuration, diagnostics, and management commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_player(self, guild: discord.Guild):
        return self.bot.player_manager.get_player(guild)

    @staticmethod
    def _valid_categories() -> str:
        return "  ".join(f"`{c}`" for c in VALID_SPONSOR_CATEGORIES)

    @staticmethod
    def _status_card(player):
        if player.sponsorblock_enabled:
            cats = "  ".join(f"`{c}`" for c in player.sponsor_categories) or "nothing"
            return notice(f"SponsorBlock **on**\n-# Skipping {cats}")
        return notice("SponsorBlock **off**", accent=MUTED)

    @app_commands.command(name="sponsorblock", description="Configure SponsorBlock skipping (ads, intros, skits)")
    @app_commands.describe(
        action="Turn SponsorBlock on, off, or inspect active skip categories",
        category="Specific category to toggle (e.g. intro, outro, music_offtopic)",
    )
    async def slash_sponsorblock(
        self,
        interaction: discord.Interaction,
        action: Literal["toggle", "status", "add_category", "remove_category"],
        category: Optional[str] = None,
    ):
        if not interaction.guild:
            return
        player = self.get_player(interaction.guild)

        if action == "toggle":
            player.sponsorblock_enabled = not player.sponsorblock_enabled
            await interaction.response.send_message(view=self._status_card(player))
            await player.refresh_now_playing_message()
            return

        if action == "status":
            await interaction.response.send_message(view=self._status_card(player))
            return

        if not category:
            await interaction.response.send_message(
                view=error_notice(f"Pick a category.\n-# {self._valid_categories()}"),
                ephemeral=True,
            )
            return

        cat_clean = category.strip().lower()
        if cat_clean not in VALID_SPONSOR_CATEGORIES:
            await interaction.response.send_message(
                view=error_notice(f"Unknown category `{discord.utils.escape_markdown(category)}`.\n-# {self._valid_categories()}"),
                ephemeral=True,
            )
            return

        if action == "add_category":
            if cat_clean not in player.sponsor_categories:
                player.sponsor_categories.append(cat_clean)
                await interaction.response.send_message(view=notice(f"Now skipping `{cat_clean}`"))
            else:
                await interaction.response.send_message(view=error_notice(f"`{cat_clean}` is already skipped."), ephemeral=True)

        elif action == "remove_category":
            if cat_clean in player.sponsor_categories:
                player.sponsor_categories.remove(cat_clean)
                await interaction.response.send_message(view=notice(f"No longer skipping `{cat_clean}`", accent=MUTED))
            else:
                await interaction.response.send_message(view=error_notice(f"`{cat_clean}` isn't being skipped."), ephemeral=True)

    @app_commands.command(name="leave", description="Disconnect the bot from the voice channel")
    async def slash_leave(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        player = self.get_player(interaction.guild)
        await player.stop()

        vc = interaction.guild.voice_client
        if vc and vc.is_connected():
            await vc.disconnect()
            await interaction.response.send_message(view=notice("-# Disconnected", accent=MUTED))
        else:
            await interaction.response.send_message(view=error_notice("Not in a voice channel."), ephemeral=True)

    @app_commands.command(name="ping", description="Check bot latency and gateway connection")
    async def slash_ping(self, interaction: discord.Interaction):
        ws_ping = round(self.bot.latency * 1000)
        vc = interaction.guild.voice_client if interaction.guild else None
        vc_ping = round(vc.average_latency * 1000) if (vc and hasattr(vc, "average_latency")) else None

        parts = [f"Gateway `{ws_ping}ms`"]
        if vc_ping is not None:
            parts.append(f"Voice `{vc_ping}ms`")
        await interaction.response.send_message(view=notice("Pong  ·  " + "  ·  ".join(parts)))

    @app_commands.command(name="help", description="Show available commands and usage guide")
    async def slash_help(self, interaction: discord.Interaction):
        await interaction.response.send_message(view=create_help_view())

    # Prefix commands
    @commands.command(name="leave", aliases=["dc", "disconnect"])
    async def prefix_leave(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        await player.stop()
        vc = ctx.guild.voice_client
        if vc and vc.is_connected():
            await vc.disconnect()
            await ctx.send(view=notice("-# Disconnected", accent=MUTED))
        else:
            await ctx.send(view=error_notice("Not in a voice channel."))

    @commands.command(name="ping")
    async def prefix_ping(self, ctx: commands.Context):
        ws_ping = round(self.bot.latency * 1000)
        await ctx.send(view=notice(f"Pong  ·  Gateway `{ws_ping}ms`"))

    @commands.command(name="sponsorblock", aliases=["sb"])
    async def prefix_sponsorblock(self, ctx: commands.Context, arg: Optional[str] = "toggle"):
        player = self.get_player(ctx.guild)
        if arg.lower() in ("toggle", "t"):
            player.sponsorblock_enabled = not player.sponsorblock_enabled
            await player.refresh_now_playing_message()
        await ctx.send(view=self._status_card(player))

    @commands.command(name="help", aliases=["commands", "h"])
    async def prefix_help(self, ctx: commands.Context):
        await ctx.send(view=create_help_view())


async def setup(bot: commands.Bot):
    await bot.add_cog(SettingsCog(bot))
