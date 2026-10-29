"""
Recommender Module.
Asks the music service for a randomized batch of tracks similar to a seed track.
Powers continuous autoplay / radio mode so playback never stops.
"""

import asyncio
import logging
from typing import List, Set, Optional
from bot import brain
from bot.audio_source import Track
from bot.config import AUTOPLAY_BATCH_SIZE

logger = logging.getLogger("AudioBot.Recommender")


class MusicRecommender:
    """Discovers similar songs for continuous autoplay and queue randomization."""

    async def get_similar_tracks(
        self,
        seed_track: Track,
        count: int = AUTOPLAY_BATCH_SIZE,
        exclude_ids: Optional[Set[str]] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> List[Track]:
        """
        Retrieves a randomized batch of tracks similar to seed_track.
        Excludes IDs in exclude_ids to avoid immediate repetitions.
        """
        seed = {"video_id": seed_track.video_id, "title": seed_track.title, "uploader": seed_track.uploader}
        try:
            data = await brain.call("/v1/recommend", {
                "seed": seed,
                "count": count,
                "exclude_ids": sorted(exclude_ids or ())[-2000:],
            })
        except brain.BrainError as e:
            logger.warning(f"No recommendations for '{seed_track.title}': {e}")
            return []

        tracks = [Track.from_brain(t, is_autoplay=True) for t in data.get("tracks") or []]
        logger.info(f"Got {len(tracks)} similar tracks based on seed '{seed_track.title}'")
        return tracks


music_recommender = MusicRecommender()
