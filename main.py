"""
Main entry point for Discord Audio Bot.
Initializes the bot client, sets up Opus audio, syncs slash commands,
loads music and settings cogs, and configures modern minimal presence.
"""

import asyncio
import logging
import os
import signal
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
    CLEAN_CHAT,
    CLEAN_CHAT_DELAY,
    CLEAN_CHAT_MENU_DELAY,
    FFMPEG_EXECUTABLE,
    resolve_ffmpeg_path,
)
from bot.player import PlayerManager
from bot import brain, channel_lock, licence, session, stay
from bot.ui import notice, MUTED

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
        self._sessions_ready = False   # nothing is saved over the file until it has been picked up again
        self._closing = False

    async def _licensed_check(self, ctx: commands.Context) -> bool:
        if not licence.licensed():
            return False
        if ctx.command and ctx.command.name == "channel":   # (so it can always be changed)
            return True
        if not channel_lock.allowed(ctx.guild.id if ctx.guild else None, ctx.channel.id):
            await ctx.send(view=notice(f"-# I only work in <#{channel_lock.channel_for(ctx.guild.id)}>", accent=MUTED))
            return False
        return True

    async def _licensed_interaction(self, interaction: discord.Interaction) -> bool:
        if not licence.licensed():
            await interaction.response.send_message(f"This bot needs a key: {licence.KEY_PAGE}", ephemeral=True)
            return False
        if interaction.command and interaction.command.name == "channel":
            return True
        if not channel_lock.allowed(interaction.guild_id, interaction.channel_id):
            await interaction.response.send_message(
                f"I only work in <#{channel_lock.channel_for(interaction.guild_id)}>", ephemeral=True)
            return False
        return True

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
        # Save what was playing first (leaving voice below empties the players)
        if self._sessions_ready and not self._closing:
            try:
                session.save_all(self.player_manager.all())
            except Exception as e:
                logger.error(f"Couldn't save the sessions: {e}")
        self._closing = True
        await brain.close()
        await super().close()

    # ---------------------------------------------------------------- saved sessions

    async def _session_saver(self):
        """Saves what each server is listening to every few seconds (and close() does at shutdown)."""
        while not self.is_closed() and not self._closing:
            try:
                session.save_all(self.player_manager.all())
            except Exception as e:
                logger.debug(f"Session save failed: {e}")
            await asyncio.sleep(15)

    async def _restore_sessions(self):
        """After a restart: rejoin each saved voice channel and carry on where it was."""
        for guild_id, s in session.load_all().items():
            guild = self.get_guild(guild_id)
            channel = guild.get_channel(s.get("voice")) if guild else None
            if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                continue
            try:
                vc = guild.voice_client
                if not vc or not vc.is_connected():
                    await channel.connect(self_deaf=True)
                elif vc.channel.id != channel.id:
                    await vc.move_to(channel)
                player = self.player_manager.get_player(guild)
                text = guild.get_channel(s.get("text")) if s.get("text") else None
                player.last_bound_channel = text
                if text and s.get("now_playing"):
                    try:
                        await text.get_partial_message(s["now_playing"]).delete()   # the card from before
                    except Exception:
                        pass
                first = session.restore_into(player, s)
                if not first:
                    continue
                start_at = float(s.get("position") or 0) if s.get("current") else 0.0
                await player.play_next(start_at=start_at if start_at > 10 else 0.0)
                if s.get("paused"):
                    player.pause()
                    await player.refresh_now_playing_message()
                if text:
                    await text.send(view=notice("-# Back after a restart: picked up where it left off", accent=MUTED))
                logger.info(f"Picked up the session in {guild.name}: '{first.title}' at {int(start_at)}s, "
                            f"{len(player.queue)} queued")
            except Exception as e:
                logger.warning(f"Couldn't pick up the session in guild {guild_id}: {e}")

    # ---------------------------------------------------------------- clean chat

    async def _tidy_later(self, message: discord.Message):
        """Clean chat: removes one of the bot's replies after a while (never the live player card)."""
        await asyncio.sleep(CLEAN_CHAT_MENU_DELAY if message.components else CLEAN_CHAT_DELAY)
        if any(p.now_playing_message and p.now_playing_message.id == message.id for p in self.player_manager.all()):
            return
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if CLEAN_CHAT and after.author.id == self.user.id and before.flags.loading and not after.flags.loading:
            self.loop.create_task(self._tidy_later(after))

    async def on_message(self, message: discord.Message):
        if not message.guild:
            return await self.process_commands(message)
        if message.author.id == self.user.id:
            if CLEAN_CHAT and not message.flags.loading:   # ("is thinking…": counted from when it's answered)
                self.loop.create_task(self._tidy_later(message))
            return
        await self.process_commands(message)
        if CLEAN_CHAT and not message.author.bot and message.content.startswith(COMMAND_PREFIX):
            ctx = await self.get_context(message)
            if ctx.valid and message.channel.permissions_for(message.guild.me).manage_messages:
                try:
                    await message.delete(delay=1)
                except discord.HTTPException:
                    pass

    async def setup_hook(self):
        """Asynchronously load extensions and synchronize slash commands."""
        self.loop.create_task(self._licence_watchdog())
        self.loop.create_task(self._stay_watchdog())
        if sys.platform != "win32":  # systemd stops the bot with SIGTERM: save the sessions first
            self.loop.add_signal_handler(signal.SIGTERM, lambda: self.loop.create_task(self.close()))

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

    async def _rejoin(self, guild_id: int, delay: float = 0.0):
        """24/7 mode: be in the saved voice channel of [guild_id] (after a restart or a dropped connection)."""
        if delay:
            await asyncio.sleep(delay)
        channel_id = stay.channel_for(guild_id)
        guild = self.get_guild(guild_id)
        if not channel_id or not guild:
            return
        vc = guild.voice_client
        if vc and vc.is_connected():
            return
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            logger.warning(f"24/7 channel {channel_id} in {guild.name} is gone; 24/7 mode turned off there")
            stay.disable(guild_id)
            return
        try:
            if vc:  # a voice client that lost its connection
                await vc.disconnect(force=True)
            await channel.connect(self_deaf=True)
            logger.info(f"24/7: joined {channel.name} in {guild.name}")
        except Exception as e:
            logger.warning(f"24/7: couldn't join {channel.name} in {guild.name}: {e}")

    async def _stay_watchdog(self):
        """24/7 mode: every few minutes, rejoin any saved channel the bot isn't in (if a rejoin failed)."""
        await self.wait_until_ready()
        if not self._sessions_ready:
            await self._restore_sessions()
            self._sessions_ready = True
            self.loop.create_task(self._session_saver())
        while not self.is_closed():
            for guild_id in stay.all_channels():
                await self._rejoin(guild_id)
            await asyncio.sleep(300)

    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Handle auto-disconnect when all other humans leave the voice channel."""
        if member.id == self.user.id:
            guild_id = member.guild.id
            if stay.channel_for(guild_id):
                if after.channel and (not before.channel or before.channel.id != after.channel.id):
                    stay.enable(guild_id, after.channel.id)  # moved: stay where it was moved to
                elif before.channel and not after.channel:
                    self.loop.create_task(self._rejoin(guild_id, delay=5))
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
