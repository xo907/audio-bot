"""
Player module for Discord Audio Bot.
Controls playback, voice client lifecycle, volume, seek, controls UI refresh,
and continuous similar-track autoplay / radio replenishment.
"""

import asyncio
import logging
import time
from typing import Optional, Dict
import discord
from discord.ext import commands

from bot.config import (
    DEFAULT_VOLUME,
    INACTIVITY_TIMEOUT,
    AUTOPLAY_DEFAULT,
    AUTOPLAY_BATCH_SIZE,
    SPONSORBLOCK_ENABLED_DEFAULT,
    DEFAULT_SPONSOR_CATEGORIES,
)
from bot.audio_source import Track, TrackExtractor, create_discord_audio_source
from bot.queue_manager import MusicQueue, LoopMode
from bot.recommender import MusicRecommender
from bot.ui import NowPlayingView, error_notice, notice, MUTED

logger = logging.getLogger("AudioBot.Player")


class GuildPlayer:
    """Manages audio playback, queue, and voice connection for a single Discord guild."""

    def __init__(self, bot: commands.Bot, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.queue = MusicQueue()
        self.recommender = MusicRecommender()
        self.extractor = TrackExtractor()

        # Settings
        self.volume: int = DEFAULT_VOLUME
        self.autoplay_enabled: bool = AUTOPLAY_DEFAULT
        self.sponsorblock_enabled: bool = SPONSORBLOCK_ENABLED_DEFAULT
        self.sponsor_categories = list(DEFAULT_SPONSOR_CATEGORIES)

        # State
        self.now_playing_message: Optional[discord.Message] = None
        self.last_bound_channel: Optional[discord.abc.Messageable] = None
        self._playback_start: float = 0.0
        self._pause_start: float = 0.0
        self._accumulated_pause: float = 0.0
        self._current_seek_offset: float = 0.0
        self._is_switching: bool = False
        self._lock = asyncio.Lock()
        self._inactivity_task: Optional[asyncio.Task] = None
        self._autoplay_fetching: bool = False

    @property
    def voice_client(self) -> Optional[discord.VoiceClient]:
        return self.guild.voice_client

    @property
    def is_connected(self) -> bool:
        vc = self.voice_client
        return vc is not None and vc.is_connected()

    @property
    def is_playing(self) -> bool:
        vc = self.voice_client
        return vc is not None and vc.is_playing()

    @property
    def is_paused(self) -> bool:
        vc = self.voice_client
        return vc is not None and vc.is_paused()

    @property
    def current_track(self) -> Optional[Track]:
        return self.queue.current_track

    @property
    def playback_position(self) -> float:
        """Calculates current elapsed playback time in seconds for progress bar rendering."""
        if not self.is_playing and not self.is_paused:
            return 0.0
        if self._playback_start <= 0:
            return 0.0

        if self.is_paused:
            now = self._pause_start
        else:
            now = time.time()

        elapsed = now - self._playback_start - self._accumulated_pause + self._current_seek_offset
        return max(0.0, elapsed)

    def pause(self) -> bool:
        vc = self.voice_client
        if vc and vc.is_playing():
            vc.pause()
            self._pause_start = time.time()
            return True
        return False

    def resume(self) -> bool:
        vc = self.voice_client
        if vc and vc.is_paused():
            vc.resume()
            if self._pause_start > 0:
                self._accumulated_pause += time.time() - self._pause_start
                self._pause_start = 0.0
            return True
        return False

    def skip(self) -> Optional[Track]:
        vc = self.voice_client
        track = self.current_track
        if vc and (vc.is_playing() or vc.is_paused()):
            # If in track loop mode, temporarily turn off to allow user skip
            if self.queue.loop_mode == LoopMode.TRACK:
                self.queue.loop_mode = LoopMode.OFF
            vc.stop()
            return track
        return None

    async def stop(self) -> None:
        self.queue.clear()
        self.queue.current_track = None
        vc = self.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        await self._delete_now_playing_message()
        self._reset_inactivity_timer()

    def set_volume(self, volume: int) -> int:
        self.volume = max(0, min(150, volume))
        vc = self.voice_client
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = self.volume / 100.0
        return self.volume

    async def seek(self, seconds: float) -> bool:
        """Restarts the current track at the specified seek offset."""
        track = self.current_track
        vc = self.voice_client
        if not track or not vc:
            return False

        if track.duration > 0 and seconds >= track.duration:
            return False

        self._is_switching = True
        try:
            source = await create_discord_audio_source(
                track=track,
                volume=self.volume,
                sponsorblock_enabled=self.sponsorblock_enabled,
                sponsor_categories=self.sponsor_categories,
                seek_seconds=seconds,
                extractor=self.extractor,
                loop=self.bot.loop,
            )

            if vc.is_playing() or vc.is_paused():
                vc.stop()

            self._playback_start = time.time()
            self._accumulated_pause = 0.0
            self._pause_start = 0.0
            self._current_seek_offset = seconds

            vc.play(source, after=lambda e: self._handle_next(e))
            await self.refresh_now_playing_message()
            return True
        except Exception as e:
            logger.error(f"Seek error for '{track.title}': {e}")
            return False
        finally:
            self._is_switching = False

    async def play_next(self) -> None:
        """Pops the next track and starts playback."""
        async with self._lock:
            vc = self.voice_client
            if not vc or not vc.is_connected():
                logger.debug("Voice client disconnected; aborting play_next.")
                return

            track = self.queue.pop_next()
            if not track:
                self.queue.current_track = None
                await self._delete_now_playing_message()
                self._reset_inactivity_timer()
                return

            self._cancel_inactivity_timer()

            try:
                audio_source = await create_discord_audio_source(
                    track=track,
                    volume=self.volume,
                    sponsorblock_enabled=self.sponsorblock_enabled,
                    sponsor_categories=self.sponsor_categories,
                    seek_seconds=0.0,
                    extractor=self.extractor,
                    loop=self.bot.loop,
                )
            except Exception as e:
                logger.error(f"Failed to create audio source for '{track.title}': {e}")
                if self.last_bound_channel:
                    try:
                        await self.last_bound_channel.send(
                            view=error_notice(f"Couldn't play **{discord.utils.escape_markdown(track.title)}**  ·  skipping")
                        )
                    except Exception:
                        pass
                # Move to next track automatically
                self.bot.loop.create_task(self.play_next())
                return

            # Start playback on voice client
            self._playback_start = time.time()
            self._accumulated_pause = 0.0
            self._pause_start = 0.0
            self._current_seek_offset = 0.0

            vc.play(audio_source, after=lambda err: self._handle_next(err))

            # Send clean Now Playing message
            await self._send_now_playing_message()

            # Ensure continuous autoplay radio buffer
            if self.autoplay_enabled:
                self.bot.loop.create_task(self.ensure_autoplay_queue())

    def _handle_next(self, error: Optional[Exception]) -> None:
        """Callback invoked by discord.py voice client when a track finishes playing."""
        if error:
            logger.error(f"Playback error in guild {self.guild.id}: {error}")

        if self._is_switching:
            return

        # Schedule next track safely on bot loop
        asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

    async def _send_now_playing_message(self) -> None:
        """Posts a fresh now-playing card, replacing the previous one."""
        if not self.last_bound_channel:
            return

        view = NowPlayingView(self)

        try:
            if self.now_playing_message:
                try:
                    await self.now_playing_message.delete()
                except Exception:
                    pass
            self.now_playing_message = await self.last_bound_channel.send(view=view)
        except Exception as e:
            logger.debug(f"Failed to send now playing message: {e}")

    async def refresh_now_playing_message(self) -> None:
        """Redraws the live now-playing card with current state (pause, progress, loop, etc.)."""
        if not self.now_playing_message:
            return
        try:
            await self.now_playing_message.edit(view=NowPlayingView(self))
        except discord.NotFound:
            self.now_playing_message = None
        except Exception as e:
            logger.debug(f"Failed to refresh now playing message: {e}")

    async def _delete_now_playing_message(self) -> None:
        if self.now_playing_message:
            try:
                await self.now_playing_message.delete()
            except Exception:
                pass
            self.now_playing_message = None

    async def set_seed_and_generate_autoplay(self, seed_track: Track) -> None:
        """
        When the user queues new music, generate a fresh batch of similar songs.
        Replaces any previously generated autoplay queue items.
        """
        if not self.autoplay_enabled:
            return

        # Clear prior autoplay recommendations
        self.queue.clear_autoplay()

        similar = await self.recommender.get_similar_tracks(
            seed_track=seed_track,
            count=AUTOPLAY_BATCH_SIZE,
            exclude_ids=self.queue.played_video_ids,
            loop=self.bot.loop,
        )

        for track in similar:
            track.is_autoplay = True
            self.queue.add(track)

        logger.info(f"Queued {len(similar)} autoplay recommendations based on '{seed_track.title}'")

    async def ensure_autoplay_queue(self) -> None:
        """Replenishes the upcoming queue with similar songs if running low."""
        if not self.autoplay_enabled or self._autoplay_fetching:
            return

        # Keep a buffer of at least 2 tracks ahead
        if len(self.queue) >= 2:
            return

        seed = self.current_track
        if not seed and self.queue.history:
            seed = self.queue.history[-1]

        if not seed:
            return

        self._autoplay_fetching = True
        try:
            similar = await self.recommender.get_similar_tracks(
                seed_track=seed,
                count=AUTOPLAY_BATCH_SIZE,
                exclude_ids=self.queue.played_video_ids,
                loop=self.bot.loop,
            )
            for track in similar:
                track.is_autoplay = True
                self.queue.add(track)
            logger.debug(f"Replenished autoplay queue with {len(similar)} tracks.")
        except Exception as e:
            logger.error(f"Error replenishing autoplay queue: {e}")
        finally:
            self._autoplay_fetching = False

    def _reset_inactivity_timer(self) -> None:
        self._cancel_inactivity_timer()
        self._inactivity_task = self.bot.loop.create_task(self._inactivity_watcher())

    def _cancel_inactivity_timer(self) -> None:
        if self._inactivity_task and not self._inactivity_task.done():
            self._inactivity_task.cancel()
            self._inactivity_task = None

    async def _inactivity_watcher(self) -> None:
        """Waits for INACTIVITY_TIMEOUT seconds before automatically leaving an empty/idle voice channel."""
        try:
            await asyncio.sleep(INACTIVITY_TIMEOUT)
            vc = self.voice_client
            if vc and vc.is_connected() and not vc.is_playing() and not vc.is_paused():
                if self.last_bound_channel:
                    try:
                        await self.last_bound_channel.send(
                            view=notice("-# Left the voice channel after inactivity", accent=MUTED)
                        )
                    except Exception:
                        pass
                await vc.disconnect()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Inactivity watcher error: {e}")


class PlayerManager:
    """Manages GuildPlayer instances across all active guilds."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._players: Dict[int, GuildPlayer] = {}

    def get_player(self, guild: discord.Guild) -> GuildPlayer:
        if guild.id not in self._players:
            self._players[guild.id] = GuildPlayer(self.bot, guild)
        return self._players[guild.id]

    def remove_player(self, guild_id: int) -> Optional[GuildPlayer]:
        return self._players.pop(guild_id, None)
