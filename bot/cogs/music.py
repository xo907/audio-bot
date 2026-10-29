"""
Music Cog module.
Implements modern slash commands and classic prefix commands for audio playback,
queue management, searching with interactive results, and continuous autoplay radio.
"""

import logging
import re
from typing import Optional, Literal, List
import discord
from discord import app_commands, ui
from discord.ext import commands

from bot.audio_source import track_extractor, Track
from bot.queue_manager import LoopMode
from bot import likes
from bot.ui import (
    LikedView,
    NowPlayingView,
    QueueView,
    SearchView,
    create_track_added_view,
    create_playlist_added_view,
    notice,
    error_notice,
    MUTED,
)

logger = logging.getLogger("AudioBot.MusicCog")


def parse_time_string(time_str: str) -> Optional[float]:
    """Parses timestamps like '1:30', '90', '01:15:00' into seconds."""
    time_str = time_str.strip()
    if re.fullmatch(r"\d+", time_str):
        return float(time_str)

    parts = time_str.split(":")
    try:
        parts = [int(p) for p in parts]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        elif len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except ValueError:
        return None
    return None


def _title(text: str) -> str:
    return discord.utils.escape_markdown(text)


class MusicCog(commands.Cog, name="Music"):
    """Core music commands for streaming, queues, and radio."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_player(self, guild: discord.Guild):
        return self.bot.player_manager.get_player(guild)

    async def _ensure_voice(self, interaction: discord.Interaction) -> Optional[tuple]:
        """
        Validates voice permissions and connects/moves bot to the user's voice channel.
        Returns (player, voice_client) or None on failure.
        """
        if not interaction.user or not isinstance(interaction.user, discord.Member):
            await interaction.followup.send(view=error_notice("This command only works in a server."), ephemeral=True)
            return None

        voice_state = interaction.user.voice
        if not voice_state or not voice_state.channel:
            await interaction.followup.send(view=error_notice("Join a voice channel first."), ephemeral=True)
            return None

        channel = voice_state.channel
        guild = interaction.guild
        if not guild:
            return None

        player = self.get_player(guild)
        player.last_bound_channel = interaction.channel

        vc = guild.voice_client
        if not vc:
            try:
                vc = await channel.connect(self_deaf=True)
            except discord.ClientException as e:
                logger.error(f"Failed to connect to voice channel: {e}")
                await interaction.followup.send(view=error_notice("Couldn't join your voice channel."), ephemeral=True)
                return None
        elif vc.channel.id != channel.id:
            await vc.move_to(channel)

        return player, vc

    def _enqueue(
        self,
        player,
        tracks: List[Track],
        playlist_title: Optional[str],
        requester: discord.Member,
    ) -> ui.LayoutView:
        """Queues extracted tracks, starts playback if idle, seeds radio, and returns the confirmation card."""
        player.queue.clear_autoplay()

        if len(tracks) > 1 or playlist_title:
            title = playlist_title or f"Collection ({len(tracks)} tracks)"
            added = player.queue.extend(tracks)
            view = create_playlist_added_view(title, added, requester, thumbnail=tracks[0].thumbnail)
        else:
            pos = len(player.queue) + 1
            player.queue.add(tracks[0])
            view = create_track_added_view(tracks[0], pos)

        return view

    async def _start(self, player, seed: Track) -> None:
        if not player.is_playing and not player.is_paused:
            await player.play_next()
        if player.autoplay_enabled:
            self.bot.loop.create_task(player.set_seed_and_generate_autoplay(seed))

    # =========================================================================
    # SLASH COMMANDS
    # =========================================================================

    @app_commands.command(name="play", description="Play audio from YouTube, Spotify, SoundCloud, or search query")
    @app_commands.describe(query="Song title, artist, YouTube URL, Spotify link, or channel URL")
    async def slash_play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(thinking=True)

        res = await self._ensure_voice(interaction)
        if not res:
            return
        player, _ = res

        try:
            tracks, playlist_title = await track_extractor.extract(
                query=query,
                requester=interaction.user,
                loop=self.bot.loop,
            )
        except Exception as e:
            logger.error(f"Extraction error for '{query}': {e}")
            await interaction.followup.send(view=error_notice(f"Couldn't load that.\n-# {e}"), ephemeral=True)
            return

        if not tracks:
            await interaction.followup.send(view=error_notice("No playable tracks found."), ephemeral=True)
            return

        view = self._enqueue(player, tracks, playlist_title, interaction.user)
        await interaction.followup.send(view=view)
        await self._start(player, tracks[0])

    async def _play_liked(self, interaction: discord.Interaction, owner, songs: List[dict]) -> None:
        """'Play all' on a liked-songs list: queues them for the person who pressed it."""
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not songs:
            await interaction.followup.send(view=error_notice("No liked songs to play."), ephemeral=True)
            return
        res = await self._ensure_voice(interaction)
        if not res:
            return
        player, _ = res
        tracks = [Track.from_brain(d, requester=interaction.user) for d in songs]
        name = "Your" if owner.id == interaction.user.id else f"{owner.display_name}'s"
        view = self._enqueue(player, tracks, f"❤️ {name} liked songs", interaction.user)
        await interaction.followup.send(view=view)
        await self._start(player, tracks[0])

    @app_commands.command(name="liked", description="See liked songs (yours, or someone else's) and play them")
    @app_commands.describe(user="Whose liked songs to show (you, if left out)")
    async def slash_liked(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        owner = user or interaction.user
        await interaction.response.send_message(
            view=LikedView(owner, likes.liked_by(owner.id), self._play_liked), ephemeral=True)

    @commands.command(name="liked", aliases=["likes"])
    async def prefix_liked(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        owner = user or ctx.author
        await ctx.send(view=LikedView(owner, likes.liked_by(owner.id), self._play_liked))

    @app_commands.command(name="search", description="Search for music and choose from a list of results")
    @app_commands.describe(query="Song title or artist to search for")
    async def slash_search(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(thinking=True)

        if not interaction.user or not isinstance(interaction.user, discord.Member):
            await interaction.followup.send(view=error_notice("This command only works in a server."), ephemeral=True)
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send(view=error_notice("Join a voice channel first."), ephemeral=True)
            return

        try:
            results = await track_extractor.search(
                query=query,
                limit=5,
                requester=interaction.user,
                loop=self.bot.loop,
            )
        except Exception as e:
            await interaction.followup.send(view=error_notice(f"Search failed.\n-# {e}"), ephemeral=True)
            return

        if not results:
            await interaction.followup.send(view=error_notice(f"No results for “{_title(query)}”."), ephemeral=True)
            return

        async def ensure_voice_for_view(view_interaction: discord.Interaction):
            res = await self._ensure_voice(view_interaction)
            return res[0] if res else None

        await interaction.followup.send(view=SearchView(query, results, ensure_voice_for_view))

    @app_commands.command(name="nowplaying", description="Show the currently playing track")
    async def slash_nowplaying(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        player = self.get_player(interaction.guild)
        if not player.current_track:
            await interaction.response.send_message(view=notice("-# Nothing is playing", accent=MUTED), ephemeral=True)
            return
        await interaction.response.send_message(view=NowPlayingView(player))

    @app_commands.command(name="queue", description="Display the current song queue")
    @app_commands.describe(page="Page number to view")
    async def slash_queue(self, interaction: discord.Interaction, page: Optional[int] = 1):
        if not interaction.guild:
            return
        player = self.get_player(interaction.guild)
        await interaction.response.send_message(view=QueueView(player.queue, page=page or 1))

    @app_commands.command(name="skip", description="Skip the current track")
    async def slash_skip(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        player = self.get_player(interaction.guild)
        skipped = player.skip()
        if skipped:
            await interaction.response.send_message(view=notice(f"Skipped **{_title(skipped.title)}**"))
        else:
            await interaction.response.send_message(view=error_notice("Nothing is playing."), ephemeral=True)

    @app_commands.command(name="pause", description="Pause playback")
    async def slash_pause(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        player = self.get_player(interaction.guild)
        if player.pause():
            await interaction.response.send_message(view=notice("Paused", accent=MUTED))
            await player.refresh_now_playing_message()
        else:
            await interaction.response.send_message(view=error_notice("Already paused or not playing."), ephemeral=True)

    @app_commands.command(name="resume", description="Resume playback")
    async def slash_resume(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        player = self.get_player(interaction.guild)
        if player.resume():
            await interaction.response.send_message(view=notice("Resumed"))
            await player.refresh_now_playing_message()
        else:
            await interaction.response.send_message(view=error_notice("Playback isn't paused."), ephemeral=True)

    @app_commands.command(name="stop", description="Stop playback and clear the queue")
    async def slash_stop(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        player = self.get_player(interaction.guild)
        await player.stop()
        await interaction.response.send_message(view=notice("Stopped  ·  queue cleared", accent=MUTED))

    @app_commands.command(name="seek", description="Seek to a specific time in the current track")
    @app_commands.describe(position="Timestamp (e.g. 1:30 or 90)")
    async def slash_seek(self, interaction: discord.Interaction, position: str):
        if not interaction.guild:
            return
        player = self.get_player(interaction.guild)
        seconds = parse_time_string(position)
        if seconds is None:
            await interaction.response.send_message(
                view=error_notice("Use a timestamp like `1:30` or `90`."), ephemeral=True
            )
            return

        await interaction.response.defer()
        success = await player.seek(seconds)
        if success:
            await interaction.followup.send(view=notice(f"Jumped to `{position}`"))
        else:
            await interaction.followup.send(view=error_notice("Couldn't seek to that position."), ephemeral=True)

    @app_commands.command(name="shuffle", description="Randomize the upcoming queue")
    async def slash_shuffle(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        player = self.get_player(interaction.guild)
        if len(player.queue) < 2:
            await interaction.response.send_message(view=error_notice("Not enough tracks to shuffle."), ephemeral=True)
            return
        player.queue.shuffle()
        await interaction.response.send_message(view=notice(f"Shuffled **{len(player.queue)}** tracks"))
        await player.refresh_now_playing_message()

    @app_commands.command(name="loop", description="Toggle loop mode")
    @app_commands.describe(mode="Choose loop mode: off, track, or queue")
    async def slash_loop(self, interaction: discord.Interaction, mode: Literal["off", "track", "queue"]):
        if not interaction.guild:
            return
        player = self.get_player(interaction.guild)
        loop_map = {
            "off": LoopMode.OFF,
            "track": LoopMode.TRACK,
            "queue": LoopMode.QUEUE,
        }
        player.queue.set_loop_mode(loop_map[mode])
        await interaction.response.send_message(view=notice(f"Loop  ·  **{mode.capitalize()}**"))
        await player.refresh_now_playing_message()

    @app_commands.command(name="clear", description="Clear all songs in the upcoming queue")
    async def slash_clear(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        player = self.get_player(interaction.guild)
        removed = player.queue.clear()
        await interaction.response.send_message(view=notice(f"Cleared **{removed}** tracks from the queue"))
        await player.refresh_now_playing_message()

    @app_commands.command(name="remove", description="Remove a specific song from the queue by its number")
    @app_commands.describe(index="Track number from /queue")
    async def slash_remove(self, interaction: discord.Interaction, index: int):
        if not interaction.guild:
            return
        player = self.get_player(interaction.guild)
        removed = player.queue.remove(index)
        if removed:
            await interaction.response.send_message(view=notice(f"Removed **{_title(removed.title)}**"))
            await player.refresh_now_playing_message()
        else:
            await interaction.response.send_message(view=error_notice(f"There's no track at `#{index}`."), ephemeral=True)

    @app_commands.command(name="volume", description="Adjust playback volume (0 - 150%)")
    @app_commands.describe(level="Volume percentage between 0 and 150")
    async def slash_volume(self, interaction: discord.Interaction, level: int):
        if not interaction.guild:
            return
        player = self.get_player(interaction.guild)
        vol = player.set_volume(level)
        await interaction.response.send_message(view=notice(f"Volume  ·  **{vol}%**"))

    @app_commands.command(name="autoplay", description="Toggle continuous radio recommendation of similar music")
    async def slash_autoplay(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        player = self.get_player(interaction.guild)
        player.autoplay_enabled = not player.autoplay_enabled
        if player.autoplay_enabled:
            await interaction.response.send_message(view=notice("Radio **on**\n-# Similar tracks will keep playing"))
        else:
            await interaction.response.send_message(view=notice("Radio **off**", accent=MUTED))
        if player.autoplay_enabled and player.current_track:
            self.bot.loop.create_task(player.ensure_autoplay_queue())
        await player.refresh_now_playing_message()

    # =========================================================================
    # CLASSIC PREFIX COMMAND ALIASES (!play, !skip, !np, !queue, etc.)
    # =========================================================================

    @commands.command(name="play", aliases=["p"])
    async def prefix_play(self, ctx: commands.Context, *, query: str):
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send(view=error_notice("Join a voice channel first."))
            return

        player = self.get_player(ctx.guild)
        player.last_bound_channel = ctx.channel

        vc = ctx.guild.voice_client
        if not vc:
            vc = await ctx.author.voice.channel.connect(self_deaf=True)
        elif vc.channel.id != ctx.author.voice.channel.id:
            await vc.move_to(ctx.author.voice.channel)

        async with ctx.typing():
            try:
                tracks, playlist_title = await track_extractor.extract(
                    query=query,
                    requester=ctx.author,
                    loop=self.bot.loop,
                )
            except Exception as e:
                await ctx.send(view=error_notice(f"Couldn't load that.\n-# {e}"))
                return

            if not tracks:
                await ctx.send(view=error_notice("No playable tracks found."))
                return

            view = self._enqueue(player, tracks, playlist_title, ctx.author)
            await ctx.send(view=view)
            await self._start(player, tracks[0])

    @commands.command(name="skip", aliases=["s", "next"])
    async def prefix_skip(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        skipped = player.skip()
        if skipped:
            await ctx.send(view=notice(f"Skipped **{_title(skipped.title)}**"))
        else:
            await ctx.send(view=error_notice("Nothing is playing."))

    @commands.command(name="nowplaying", aliases=["np"])
    async def prefix_nowplaying(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        if not player.current_track:
            await ctx.send(view=notice("-# Nothing is playing", accent=MUTED))
            return
        await ctx.send(view=NowPlayingView(player))

    @commands.command(name="queue", aliases=["q"])
    async def prefix_queue(self, ctx: commands.Context, page: Optional[int] = 1):
        player = self.get_player(ctx.guild)
        await ctx.send(view=QueueView(player.queue, page=page or 1))

    @commands.command(name="pause")
    async def prefix_pause(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        if player.pause():
            await ctx.send(view=notice("Paused", accent=MUTED))
            await player.refresh_now_playing_message()

    @commands.command(name="resume")
    async def prefix_resume(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        if player.resume():
            await ctx.send(view=notice("Resumed"))
            await player.refresh_now_playing_message()

    @commands.command(name="stop")
    async def prefix_stop(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        await player.stop()
        await ctx.send(view=notice("Stopped  ·  queue cleared", accent=MUTED))

    @commands.command(name="shuffle")
    async def prefix_shuffle(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        if len(player.queue) < 2:
            await ctx.send(view=error_notice("Not enough tracks to shuffle."))
            return
        player.queue.shuffle()
        await ctx.send(view=notice(f"Shuffled **{len(player.queue)}** tracks"))
        await player.refresh_now_playing_message()

    @commands.command(name="volume", aliases=["vol", "v"])
    async def prefix_volume(self, ctx: commands.Context, level: int):
        player = self.get_player(ctx.guild)
        vol = player.set_volume(level)
        await ctx.send(view=notice(f"Volume  ·  **{vol}%**"))

    @commands.command(name="autoplay", aliases=["radio"])
    async def prefix_autoplay(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        player.autoplay_enabled = not player.autoplay_enabled
        if player.autoplay_enabled:
            await ctx.send(view=notice("Radio **on**\n-# Similar tracks will keep playing"))
        else:
            await ctx.send(view=notice("Radio **off**", accent=MUTED))
        if player.autoplay_enabled and player.current_track:
            self.bot.loop.create_task(player.ensure_autoplay_queue())
        await player.refresh_now_playing_message()


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
