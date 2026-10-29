"""
Main entry point for Discord Audio Bot.
Initializes the bot client, sets up Opus audio, syncs slash commands,
loads music and settings cogs, and configures modern minimal presence.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
import discord
from discord.ext import commands

# 1. Force UTF-8 on Windows consoles to prevent UnicodeEncodeError
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# 2. Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("AudioBot")

from bot.config import (
    DISCORD_TOKEN,
    COMMAND_PREFIX,
    FFMPEG_EXECUTABLE,
    resolve_ffmpeg_path,
)
from bot.player import PlayerManager
from bot import brain, licence

# 3. Ensure Opus is loaded for Discord voice
if not discord.opus.is_loaded():
    try:
        discord.opus._load_default()
    except Exception:
        pass


class AudioBot(commands.Bot):
    """Custom Discord Bot client subclass with PlayerManager integration."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.guilds = True

        super().__init__(
            command_prefix=COMMAND_PREFIX,
            intents=intents,
            help_command=None,  # We provide custom clean /help
        )
        self.player_manager = PlayerManager(self)

        # Nothing runs without a valid licence (main() checks before logging in; this catches a key
        # revoked while the bot is running, until the watchdog below shuts it down).
        self.add_check(self._licensed_check)
        self.tree.interaction_check = self._licensed_interaction

    async def _licensed_check(self, ctx: commands.Context) -> bool:
        return licence.licensed()

    async def _licensed_interaction(self, interaction: discord.Interaction) -> bool:
        if licence.licensed():
            return True
        await interaction.response.send_message(f"This bot needs a key: {licence.KEY_PAGE}", ephemeral=True)
        return False

    async def _licence_watchdog(self):
        """Renews the licence about once a day; a revoked or expired key shuts the bot down."""
        while not self.is_closed():
            await asyncio.sleep(6 * 3600)
            await asyncio.to_thread(licence.renew_if_due)
            if not licence.licensed():
                logger.error(f"The licence is no longer valid. Get a key at {licence.KEY_PAGE}")
                await self.close()
                return

    async def close(self):
        await brain.close()
        await super().close()

    async def setup_hook(self):
        """Asynchronously load extensions and synchronize slash commands."""
        self.loop.create_task(self._licence_watchdog())

        # Load cogs
        cogs = [
            "bot.cogs.music",
            "bot.cogs.settings",
        ]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"Loaded extension: {cog}")
            except Exception as e:
                logger.error(f"Failed to load extension {cog}: {e}", exc_info=True)

        # Synchronize slash commands globally
        logger.info("Synchronizing application slash commands with Discord...")
        try:
            synced = await self.tree.sync()
            logger.info(f"Successfully synced {len(synced)} slash commands.")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")

    async def on_ready(self):
        logger.info(f"════════════════════════════════════════════")
        logger.info(f"Logged in as: {self.user.name} ({self.user.id})")
        logger.info(f"Connected to: {len(self.guilds)} guild(s)")
        logger.info(f"FFmpeg path:  {FFMPEG_EXECUTABLE}")
        logger.info(f"Opus loaded:  {discord.opus.is_loaded()}")
        logger.info(f"Prefix:       {COMMAND_PREFIX}")
        logger.info(f"════════════════════════════════════════════")

        # Set clean presence
        activity = discord.Activity(
            type=discord.ActivityType.listening,
            name="/play • /search",
        )
        await self.change_presence(status=discord.Status.online, activity=activity)

    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Handle auto-disconnect when all other humans leave the voice channel."""
        if member.id == self.user.id:
            # If bot was disconnected externally by an admin
            if before.channel and not after.channel:
                player = self.player_manager.remove_player(before.channel.guild.id)
                if player:
                    await player.stop()
            return

        # Check if bot is left alone in the voice channel
        guild = member.guild
        vc = guild.voice_client
        if vc and vc.channel:
            human_members = [m for m in vc.channel.members if not m.bot]
            if len(human_members) == 0:
                player = self.player_manager.get_player(guild)
                player._reset_inactivity_timer()


def _stop(lines):
    print("\n" + "=" * 60)
    for line in lines:
        print(f" {line}")
    print("=" * 60 + "\n")
    sys.exit(2)  # a setup problem (key or token): restarting won't help


def ensure_licence():
    """Exits unless this bot has a valid licence (activating LICENSE_KEY, or asking for a key)."""
    licence.load()
    env_key = os.getenv("LICENSE_KEY", "").strip().upper()
    if licence.licensed() and (not env_key or env_key == licence.stored_key()):
        licence.renew_if_due()
    elif licence.stored_key() and not env_key:
        licence.renew_if_due(force=True)  # e.g. a licence that ran out while offline
    if licence.licensed():
        s = licence.status()
        logger.info(f"Licence OK ({s['tier']}, key …{s['key_end']})")
        return

    key = env_key
    if not key and sys.stdin and sys.stdin.isatty():
        print(f"\nThis bot needs a key. Get yours at: {licence.KEY_PAGE}")
        try:
            key = input("Paste your key: ").strip()
        except EOFError:
            key = ""
    if not key:
        _stop([
            "[!] This bot needs a key to run.",
            f" Get yours at: {licence.KEY_PAGE}",
            " Then put it in .env as LICENSE_KEY=SAVEX-XXXXX-XXXXX-XXXXX-XXXXX",
        ])
    try:
        s = licence.activate(key)
    except licence.LicenceError as e:
        _stop([f"[!] {e}", f" Keys come from: {licence.KEY_PAGE}"])
    logger.info(f"Key activated ({s['tier']}, key …{s['key_end']})")


def main():
    if "--remove-key" in sys.argv:
        licence.deactivate()
        print("The key was removed from this bot. Its place on the key is free again.")
        return

    if not DISCORD_TOKEN or DISCORD_TOKEN.strip() == "YOUR_DISCORD_BOT_TOKEN_HERE":
        print("\n" + "=" * 60)
        print(" [!] DISCORD_TOKEN is missing or not configured in .env")
        print(" Please open the '.env' file in this folder and paste")
        print(" your Discord Bot Token, then run again.")
        print("=" * 60 + "\n")
        sys.exit(2)  # a setup problem (key or token): restarting won't help

    ensure_licence()
    bot = AudioBot()

    try:
        bot.run(DISCORD_TOKEN, log_handler=None)
    except discord.LoginFailure:
        print("\n" + "=" * 60)
        print(" [!] Invalid Discord Bot Token.")
        print(" Please verify the DISCORD_TOKEN value in your .env file.")
        print("=" * 60 + "\n")
        sys.exit(2)  # a setup problem (key or token): restarting won't help
    except KeyboardInterrupt:
        print("\nShutting down bot cleanly...")


if __name__ == "__main__":
    main()
