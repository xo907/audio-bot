"""
Audio source module.
Finds tracks through the music service (bot/brain.py), resolves direct streams locally with yt-dlp,
and constructs high-fidelity Discord FFmpeg audio sources with SponsorBlock skips applied.
"""

import asyncio
import logging
import time
from typing import Optional, List, Dict, Any, Tuple
import discord
import yt_dlp
from bot.config import FFMPEG_EXECUTABLE, DEFAULT_SPONSOR_CATEGORIES
from bot import brain

logger = logging.getLogger("AudioBot.AudioSource")

# Base yt-dlp configuration optimized for fast audio extraction and high reliability
YTDL_OPTIONS: Dict[str, Any] = {
    "format": "bestaudio/best",
    "extract_flat": False,
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",  # bind to ipv4
    "skip_download": True,
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web"]
        }
    },
    "postprocessors": [],
}


class Track:
    """Represents an individual audio track in queue."""

    def __init__(
        self,
        title: str,
        webpage_url: str,
        duration: int = 0,
        thumbnail: Optional[str] = None,
        uploader: Optional[str] = None,
        requester: Optional[discord.Member] = None,
        video_id: Optional[str] = None,
        stream_url: Optional[str] = None,
        source_type: str = "youtube",
        search_query: Optional[str] = None,
        is_autoplay: bool = False,
    ):
        self.title = title
        self.webpage_url = webpage_url
        self.duration = duration
        self.thumbnail = thumbnail
        self.uploader = uploader or "Unknown Artist"
        self.requester = requester
        self.video_id = video_id
        self.stream_url = stream_url
        self.stream_url_expiry = 0.0
        self.source_type = source_type
        self.search_query = search_query
        self.is_autoplay = is_autoplay

        # SponsorBlock details
        self.sponsor_segments: List[Dict[str, Any]] = []
        self.skipped_descriptions: List[str] = []
        self.effective_start: float = 0.0

    @property
    def formatted_duration(self) -> str:
        if not self.duration or self.duration <= 0:
            return "Live Stream"
        minutes, seconds = divmod(int(self.duration), 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    def is_stream_url_valid(self) -> bool:
        return bool(self.stream_url and (time.time() < self.stream_url_expiry - 120))

    @classmethod
    def from_brain(cls, data: Dict[str, Any], requester: Optional[discord.Member] = None, is_autoplay: bool = False) -> "Track":
        return cls(
            title=data.get("title") or "Unknown Track",
            webpage_url=data["webpage_url"],
            duration=int(data.get("duration") or 0),
            thumbnail=data.get("thumbnail"),
            uploader=data.get("uploader"),
            requester=requester,
            video_id=data.get("video_id"),
            source_type=data.get("source_type") or "youtube",
            search_query=data.get("search_query"),
            is_autoplay=is_autoplay,
        )


class TrackExtractor:
    """Handles extracting and preparing tracks from various sources."""

    def __init__(self):
        self.ydl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

    async def search(
        self,
        query: str,
        limit: int = 5,
        requester: Optional[discord.Member] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> List[Track]:
        """
        Searches for tracks matching query and returns a list of results.
        """
        data = await brain.call("/v1/search", {"query": query, "limit": max(1, min(10, limit))})
        return [Track.from_brain(t, requester) for t in data.get("tracks") or []]

    async def extract(
        self,
        query: str,
        requester: Optional[discord.Member] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> Tuple[List[Track], Optional[str]]:
        """
        Extracts tracks from user query (URL, Spotify link, search term, channel, or playlist).
        Returns (tracks_list, playlist_title).
        """
        data = await brain.call("/v1/resolve", {"query": query.strip()}, timeout=120.0)
        tracks = [Track.from_brain(t, requester) for t in data.get("tracks") or []]
        return tracks, data.get("playlist_title")

    async def ensure_stream_url(
        self,
        track: Track,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        """Ensures the track has a valid, non-expired direct audio stream URL."""
        if track.is_stream_url_valid():
            return

        loop = loop or asyncio.get_event_loop()
        target = track.webpage_url
        if track.source_type == "spotify" and track.search_query:
            matched = (await brain.call("/v1/match", {"query": track.search_query})).get("track")
            if not matched:
                raise RuntimeError(f"No match found for '{track.title}'.")
            target = matched["webpage_url"]

        try:
            info = await loop.run_in_executor(
                None, lambda: self.ydl.extract_info(target, download=False)
            )
            if "entries" in info:
                entries = [e for e in info["entries"] if e]
                if entries:
                    info = entries[0]

            track.stream_url = info.get("url")
            track.stream_url_expiry = time.time() + 3600
            if not track.video_id:
                track.video_id = info.get("id")
            if not track.duration or track.duration == 0:
                track.duration = int(info.get("duration") or 0)
            if not track.thumbnail:
                track.thumbnail = info.get("thumbnail")
        except Exception as e:
            logger.error(f"Failed to refresh stream URL for '{track.title}': {e}")
            raise RuntimeError(f"Could not retrieve audio stream: {e}")


async def create_discord_audio_source(
    track: Track,
    volume: int = 100,
    sponsorblock_enabled: bool = True,
    sponsor_categories: Optional[List[str]] = None,
    seek_seconds: float = 0.0,
    extractor: Optional[TrackExtractor] = None,
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> discord.AudioSource:
    """
    Constructs a discord.PCMVolumeTransformer wrapping discord.FFmpegPCMAudio,
    applying SponsorBlock segment filters and initial seek offsets.
    """
    loop = loop or asyncio.get_event_loop()
    extractor = extractor or TrackExtractor()

    # Step 1: Ensure direct audio stream URL
    await extractor.ensure_stream_url(track, loop)
    if not track.stream_url:
        raise RuntimeError("No direct audio stream URL found.")

    # Step 2: SponsorBlock processing
    track.sponsor_segments = []
    track.skipped_descriptions = []
    effective_start = seek_seconds
    audio_filter = None

    if sponsorblock_enabled and track.video_id:
        categories = sponsor_categories or DEFAULT_SPONSOR_CATEGORIES
        try:
            skips = await brain.call(
                "/v1/segments",
                {"video_id": track.video_id, "categories": categories, "seek": seek_seconds},
                timeout=10.0,
            )
            effective_start = float(skips.get("start") or seek_seconds)
            audio_filter = skips.get("filter")
            track.skipped_descriptions = skips.get("skipped") or []
            track.effective_start = effective_start
        except brain.BrainError as e:
            logger.debug(f"SponsorBlock skipped for '{track.title}': {e}")

    # Step 3: FFmpeg arguments
    # Reconnect options prevent stream drops over network
    before_args = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin"
    if effective_start > 0:
        before_args += f" -ss {effective_start:.2f}"

    ffmpeg_options = "-vn"
    if audio_filter:
        ffmpeg_options += f" -af \"{audio_filter}\""

    # Step 4: Create FFmpeg audio source
    raw_source = discord.FFmpegPCMAudio(
        track.stream_url,
        executable=FFMPEG_EXECUTABLE,
        before_options=before_args,
        options=ffmpeg_options,
    )

    # Step 5: Volume transformer (0.0 to 1.5)
    normalized_volume = max(0.0, min(1.5, volume / 100.0))
    return discord.PCMVolumeTransformer(raw_source, volume=normalized_volume)


track_extractor = TrackExtractor()
