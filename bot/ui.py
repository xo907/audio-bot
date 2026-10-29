"""
UI module for Discord Audio Bot.
Minimal cards built on Discord's Components V2: accent-coloured containers,
sections with thumbnails, subtle subtext, and controls that update in place.
"""

import time
from typing import Optional, List, TYPE_CHECKING
import discord
from discord import ui
from bot import likes
from bot.audio_source import Track
from bot.queue_manager import MusicQueue, LoopMode

if TYPE_CHECKING:
    from bot.player import GuildPlayer

# Palette: one soft accent, a muted grey for idle/paused states, and a gentle red for errors
ACCENT = discord.Colour.from_rgb(124, 131, 253)
MUTED = discord.Colour.from_rgb(78, 80, 88)
ERROR = discord.Colour.from_rgb(224, 108, 117)

QUEUE_PAGE_SIZE = 10


# =========================================================================
# FORMATTING HELPERS
# =========================================================================

def generate_progress_bar(current_sec: float, total_sec: float, length: int = 18) -> str:
    """Generates a thin, modern progress bar."""
    if total_sec <= 0:
        return "● LIVE"
    prog = max(0.0, min(1.0, current_sec / total_sec))
    idx = int(round(prog * (length - 1)))
    return "━" * idx + "●" + "─" * (length - 1 - idx)


def format_seconds(seconds: float) -> str:
    """Formats seconds into MM:SS or HH:MM:SS."""
    if seconds <= 0:
        return "0:00"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _link(track: Track, limit: int = 80) -> str:
    """Markdown link to a track with brackets and markdown escaped."""
    title = discord.utils.escape_markdown(_truncate(track.title, limit))
    title = title.replace("[", "(").replace("]", ")")
    return f"[{title}]({track.webpage_url})" if track.webpage_url else title


def _artist(track: Track, limit: int = 60) -> str:
    return discord.utils.escape_markdown(_truncate(track.uploader or "Unknown Artist", limit))


def _join(*parts: Optional[str]) -> str:
    return "  ·  ".join(p for p in parts if p)


def _with_thumbnail(text: str, thumbnail: Optional[str]) -> ui.Item:
    """A text block with the artwork floated to the right, when there is artwork."""
    if thumbnail:
        return ui.Section(ui.TextDisplay(text), accessory=ui.Thumbnail(thumbnail))
    return ui.TextDisplay(text)


# =========================================================================
# GENERIC CARDS
# =========================================================================

def card(*items: ui.Item, accent: discord.Colour = ACCENT, timeout: Optional[float] = None) -> ui.LayoutView:
    """Wraps items in a single accent-coloured container."""
    view = ui.LayoutView(timeout=timeout)
    view.add_item(ui.Container(*items, accent_colour=accent))
    return view


def notice(text: str, *, accent: discord.Colour = ACCENT) -> ui.LayoutView:
    """A one-line status card."""
    return card(ui.TextDisplay(text), accent=accent)


def error_notice(text: str) -> ui.LayoutView:
    """A one-line error card."""
    return notice(text, accent=ERROR)


def create_track_added_view(track: Track, queue_position: int) -> ui.LayoutView:
    """Compact 'added to queue' card."""
    text = (
        f"-# Added to queue  ·  #{queue_position}\n"
        f"**{_link(track)}**\n"
        f"-# {_join(_artist(track), track.formatted_duration)}"
    )
    return card(_with_thumbnail(text, track.thumbnail))


def create_playlist_added_view(
    title: str,
    track_count: int,
    requester: Optional[discord.Member] = None,
    thumbnail: Optional[str] = None,
) -> ui.LayoutView:
    """Compact 'playlist queued' card."""
    text = (
        f"-# Added to queue\n"
        f"**{discord.utils.escape_markdown(_truncate(title, 80))}**\n"
        f"-# {_join(f'{track_count} tracks', requester and f'by {requester.display_name}')}"
    )
    return card(_with_thumbnail(text, thumbnail))


def create_help_view() -> ui.LayoutView:
    """Clean, grouped command reference."""
    return card(
        ui.TextDisplay("## Commands"),
        ui.TextDisplay(
            "-# Playback\n"
            "`/play` Play a song, link, or playlist\n"
            "`/search` Pick from search results\n"
            "`/pause`  `/resume`  `/skip`  `/stop`  `/seek`"
        ),
        ui.Separator(),
        ui.TextDisplay(
            "-# Queue\n"
            "`/nowplaying` Player with controls\n"
            "`/queue` Upcoming tracks\n"
            "`/liked` Your liked songs (❤️ on the player)\n"
            "`/shuffle`  `/loop`  `/remove`  `/clear`"
        ),
        ui.Separator(),
        ui.TextDisplay(
            "-# Settings\n"
            "`/autoplay` Keep playing similar music\n"
            "`/sponsorblock` Skip sponsors, intros, and filler\n"
            "`/stay` 24/7: never leave the voice channel\n"
            "`/channel` Only work in this channel\n"
            "`/volume`  `/ping`  `/leave`"
        ),
    )


# =========================================================================
# NOW PLAYING
# =========================================================================

async def _check_member(interaction: discord.Interaction) -> bool:
    """Only listeners in the bot's voice channel may use the controls."""
    if not isinstance(interaction.user, discord.Member):
        return False
    user_voice = interaction.user.voice
    bot_voice = interaction.guild.voice_client if interaction.guild else None

    if not user_voice or not user_voice.channel:
        await interaction.response.send_message(
            view=error_notice("Join a voice channel to use the controls."), ephemeral=True
        )
        return False

    if bot_voice and user_voice.channel.id != bot_voice.channel.id:
        await interaction.response.send_message(
            view=error_notice("You need to be in the same voice channel as the bot."), ephemeral=True
        )
        return False

    return True


class NowPlayingView(ui.LayoutView):
    """The player card: artwork, progress, inline controls, and what's up next."""

    def __init__(self, player: "GuildPlayer"):
        super().__init__(timeout=None)
        self.player = player
        track = player.current_track
        if not track:
            self.add_item(ui.Container(ui.TextDisplay("-# Nothing is playing"), accent_colour=MUTED))
            return

        paused = player.is_paused
        container = ui.Container(accent_colour=MUTED if paused else ACCENT)

        # Header: state, title, artist, progress
        position = player.playback_position
        progress = f"`{format_seconds(position)}`  {generate_progress_bar(position, track.duration)}  `{track.formatted_duration}`"
        header = (
            f"-# {'Paused' if paused else 'Now playing'}\n"
            f"### {_link(track)}\n"
            f"{_artist(track)}\n"
            f"{progress}"
        )
        container.add_item(_with_thumbnail(header, track.thumbnail))

        # Controls
        loop_mode = player.queue.loop_mode
        controls = ui.ActionRow(
            self._button("▶️" if paused else "⏸️", self._toggle_pause, active=paused),
            self._button("⏭️", self._skip),
            self._button("⏹️", self._stop),
            self._button("🔂" if loop_mode == LoopMode.TRACK else "🔁", self._loop, active=loop_mode != LoopMode.OFF),
            self._button("📻", self._radio, active=player.autoplay_enabled),
        )
        container.add_item(controls)
        container.add_item(ui.Separator())

        # Up next, with the full queue one click away
        upcoming = player.queue.tracks
        if upcoming:
            nxt = upcoming[0]
            up_next = f"-# Up next\n{_link(nxt, 50)}  ·  {_artist(nxt, 30)}"
        else:
            up_next = "-# Up next\nNothing queued"
        queue_button = ui.Button(
            label=f"Queue  {len(upcoming)}" if upcoming else "Queue",
            style=discord.ButtonStyle.secondary,
        )
        queue_button.callback = self._show_queue
        container.add_item(ui.Section(ui.TextDisplay(up_next), accessory=queue_button))

        # Status line
        status = []
        if track.requester:
            status.append(f"Requested by {track.requester.display_name}")
        elif track.is_autoplay:
            status.append("From radio")
        if loop_mode == LoopMode.TRACK:
            status.append("Looping track")
        elif loop_mode == LoopMode.QUEUE:
            status.append("Looping queue")
        if player.sponsorblock_enabled and track.skipped_descriptions:
            n = len(track.skipped_descriptions)
            status.append(f"{n} segment{'s' if n != 1 else ''} skipped")
        if not paused and track.duration > 0:
            ends_at = int(time.time() + max(0.0, track.duration - position))
            status.append(f"Ends <t:{ends_at}:R>")
        if status:
            container.add_item(ui.TextDisplay(f"-# {_join(*status)}"))

        # Likes: who liked this song, and the button to like it (anyone can, not only listeners)
        self.track = track
        who = likes.likers(track)
        if who:
            names = ", ".join(f"<@{uid}>" for uid in who[:5]) + (f" +{len(who) - 5} more" if len(who) > 5 else "")
            liked_line = f"-# Liked by {names}"
        else:
            liked_line = "-# No likes yet"
        like_button = ui.Button(emoji="❤️", label=str(len(who)) if who else None,
                                style=discord.ButtonStyle.secondary, custom_id="np:like")
        like_button.callback = self._like
        container.add_item(ui.Section(ui.TextDisplay(liked_line), accessory=like_button))

        self.add_item(container)

    @staticmethod
    def _button(emoji: str, callback, active: bool = False) -> ui.Button:
        button = ui.Button(
            emoji=emoji,
            style=discord.ButtonStyle.primary if active else discord.ButtonStyle.secondary,
        )
        button.callback = callback
        return button

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (interaction.data or {}).get("custom_id") == "np:like":
            return True
        return await _check_member(interaction)

    async def _like(self, interaction: discord.Interaction):
        liked = likes.toggle(interaction.user.id, self.track)
        await self._rerender(interaction)
        await interaction.followup.send(
            view=notice(f"❤️ Added to your liked songs\n-# `/liked` to see them all" if liked
                        else "-# Removed from your liked songs", accent=ACCENT if liked else MUTED),
            ephemeral=True)

    async def _rerender(self, interaction: discord.Interaction) -> None:
        """Redraw the card that was clicked, plus the live player card if it's a different message."""
        await interaction.response.edit_message(view=NowPlayingView(self.player))
        live = self.player.now_playing_message
        if live and interaction.message and live.id != interaction.message.id:
            await self.player.refresh_now_playing_message()

    async def _toggle_pause(self, interaction: discord.Interaction):
        if self.player.is_paused:
            self.player.resume()
        else:
            self.player.pause()
        await self._rerender(interaction)

    async def _skip(self, interaction: discord.Interaction):
        if not self.player.skip():
            await interaction.response.send_message(view=error_notice("Nothing is playing."), ephemeral=True)
            return
        # The player posts a fresh card for the next track
        await interaction.response.defer()

    async def _stop(self, interaction: discord.Interaction):
        # Keep the clicked card around as a 'stopped' notice instead of deleting it
        live = self.player.now_playing_message
        if live and interaction.message and live.id == interaction.message.id:
            self.player.now_playing_message = None
        await interaction.response.edit_message(
            view=notice(f"-# Stopped by {interaction.user.display_name}  ·  queue cleared", accent=MUTED)
        )
        await self.player.stop()

    async def _loop(self, interaction: discord.Interaction):
        self.player.queue.toggle_loop()
        await self._rerender(interaction)

    async def _radio(self, interaction: discord.Interaction):
        self.player.autoplay_enabled = not self.player.autoplay_enabled
        if self.player.autoplay_enabled and self.player.current_track:
            self.player.bot.loop.create_task(self.player.ensure_autoplay_queue())
        await self._rerender(interaction)

    async def _show_queue(self, interaction: discord.Interaction):
        await interaction.response.send_message(view=QueueView(self.player.queue), ephemeral=True)


def create_now_playing_view(player: "GuildPlayer") -> NowPlayingView:
    return NowPlayingView(player)


# =========================================================================
# QUEUE
# =========================================================================

class QueueView(ui.LayoutView):
    """Paginated queue card with in-place page navigation."""

    def __init__(self, queue: MusicQueue, page: int = 1):
        super().__init__(timeout=300.0)
        self.queue = queue
        tracks_slice, total_pages, current_page = queue.get_page(page, page_size=QUEUE_PAGE_SIZE)
        self.page = current_page

        container = ui.Container(accent_colour=ACCENT)
        count = len(queue)
        container.add_item(ui.TextDisplay(
            f"-# Queue  ·  {count} track{'s' if count != 1 else ''}  ·  {queue.formatted_total_duration}"
        ))

        cur = queue.current_track
        if cur:
            now = (
                f"**{_link(cur, 60)}**\n"
                f"-# {_join('Now playing', _artist(cur, 40), cur.formatted_duration)}"
            )
            container.add_item(_with_thumbnail(now, cur.thumbnail))

        if tracks_slice:
            container.add_item(ui.Separator())
            start = (current_page - 1) * QUEUE_PAGE_SIZE
            width = len(str(start + len(tracks_slice)))
            lines = []
            for i, t in enumerate(tracks_slice, start=start + 1):
                tag = "  ·  radio" if t.is_autoplay else ""
                lines.append(f"`{i:>{width}}`  {_link(t, 45)}  ·  {_artist(t, 25)}  `{t.formatted_duration}`{tag}")
            container.add_item(ui.TextDisplay("\n".join(lines)))
        elif not cur:
            container.add_item(ui.TextDisplay("Nothing queued yet. Use `/play` to add music."))

        if total_pages > 1:
            prev_btn = ui.Button(emoji="◀️", style=discord.ButtonStyle.secondary, disabled=current_page <= 1)
            next_btn = ui.Button(emoji="▶️", style=discord.ButtonStyle.secondary, disabled=current_page >= total_pages)
            prev_btn.callback = self._prev
            next_btn.callback = self._next
            container.add_item(ui.Separator())
            container.add_item(ui.ActionRow(
                prev_btn,
                ui.Button(label=f"{current_page} / {total_pages}", style=discord.ButtonStyle.secondary, disabled=True),
                next_btn,
            ))

        self.add_item(container)

    async def _prev(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=QueueView(self.queue, self.page - 1))

    async def _next(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=QueueView(self.queue, self.page + 1))


# =========================================================================
# LIKED SONGS
# =========================================================================

class LikedView(ui.LayoutView):
    """Someone's liked songs, a page at a time, with a button to queue them all."""

    def __init__(self, owner: discord.abc.User, songs: List[dict], play_all, page: int = 1):
        super().__init__(timeout=300.0)
        self.owner, self.songs, self.play_all = owner, songs, play_all
        total_pages = max(1, -(-len(songs) // QUEUE_PAGE_SIZE))
        self.page = page = max(1, min(page, total_pages))

        container = ui.Container(accent_colour=ACCENT)
        count = len(songs)
        container.add_item(ui.TextDisplay(
            f"-# ❤️ Liked songs  ·  {owner.mention}  ·  {count} song{'s' if count != 1 else ''}"))
        if not songs:
            container.add_item(ui.TextDisplay("Nothing liked yet. Press ❤️ on the player to like a song."))
        else:
            container.add_item(ui.Separator())
            start = (page - 1) * QUEUE_PAGE_SIZE
            chunk = songs[start:start + QUEUE_PAGE_SIZE]
            width = len(str(start + len(chunk)))
            lines = []
            for i, d in enumerate(chunk, start=start + 1):
                t = Track.from_brain(d)
                lines.append(f"`{i:>{width}}`  {_link(t, 45)}  ·  {_artist(t, 25)}  `{t.formatted_duration}`")
            container.add_item(ui.TextDisplay("\n".join(lines)))
            container.add_item(ui.Separator())
            play = ui.Button(emoji="▶️", label=f"Play all {count}", style=discord.ButtonStyle.primary)
            play.callback = self._play
            row = [play]
            if total_pages > 1:
                prev_btn = ui.Button(emoji="◀️", style=discord.ButtonStyle.secondary, disabled=page <= 1)
                next_btn = ui.Button(emoji="▶️", style=discord.ButtonStyle.secondary, disabled=page >= total_pages)
                prev_btn.callback, next_btn.callback = self._prev, self._next
                row += [prev_btn, ui.Button(label=f"{page} / {total_pages}", style=discord.ButtonStyle.secondary,
                                            disabled=True), next_btn]
            container.add_item(ui.ActionRow(*row))
        self.add_item(container)

    async def _prev(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=LikedView(self.owner, self.songs, self.play_all, self.page - 1))

    async def _next(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=LikedView(self.owner, self.songs, self.play_all, self.page + 1))

    async def _play(self, interaction: discord.Interaction):
        await self.play_all(interaction, self.owner, self.songs)


# =========================================================================
# SEARCH
# =========================================================================

class SearchView(ui.LayoutView):
    """Search results, each with its own play button."""

    def __init__(self, query: str, tracks: List[Track], ensure_voice_func):
        super().__init__(timeout=60.0)
        self.tracks = tracks
        self.ensure_voice = ensure_voice_func

        container = ui.Container(accent_colour=ACCENT)
        container.add_item(ui.TextDisplay(
            f"-# Results for “{discord.utils.escape_markdown(_truncate(query, 60))}”"
        ))
        for i, t in enumerate(tracks):
            play = ui.Button(emoji="▶️", style=discord.ButtonStyle.secondary)
            play.callback = self._make_callback(i)
            text = f"**{_link(t, 60)}**\n-# {_join(_artist(t, 40), t.formatted_duration)}"
            container.add_item(ui.Section(ui.TextDisplay(text), accessory=play))

        cancel = ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        cancel.callback = self._cancel
        container.add_item(ui.Separator())
        container.add_item(ui.ActionRow(cancel))
        self.add_item(container)

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            await self._choose(interaction, self.tracks[index])
        return callback

    async def _choose(self, interaction: discord.Interaction, chosen_track: Track):
        # Joining voice can take a moment, so acknowledge first
        await interaction.response.defer()
        player = await self.ensure_voice(interaction)
        if not player:
            return

        chosen_track.requester = interaction.user
        chosen_track.is_autoplay = False

        # Clear old autoplay tracks on new user selection
        player.queue.clear_autoplay()

        pos = len(player.queue) + 1
        player.queue.add(chosen_track)
        self.stop()

        await interaction.edit_original_response(view=create_track_added_view(chosen_track, pos))

        if not player.is_playing and not player.is_paused:
            await player.play_next()

        if player.autoplay_enabled:
            player.bot.loop.create_task(player.set_seed_and_generate_autoplay(chosen_track))

    async def _cancel(self, interaction: discord.Interaction):
        self.stop()
        await interaction.response.edit_message(view=notice("-# Search cancelled", accent=MUTED))
