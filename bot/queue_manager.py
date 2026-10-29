"""
Queue Manager module.
Manages playback queue, track history, loop modes (Off, Track, Queue), shuffling, and autoplay tracking.
"""

from enum import Enum
import random
from typing import List, Optional, Tuple, Set
from collections import deque
from bot.audio_source import Track
from bot.config import MAX_QUEUE_SIZE


class LoopMode(str, Enum):
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"


class MusicQueue:
    """Manages the queue of songs for a Discord guild."""

    def __init__(self, max_size: int = MAX_QUEUE_SIZE):
        self._queue: deque[Track] = deque()
        self.history: List[Track] = []
        self.current_track: Optional[Track] = None
        self.loop_mode: LoopMode = LoopMode.OFF
        self.max_size = max_size
        self.played_video_ids: Set[str] = set()

    def __len__(self) -> int:
        return len(self._queue)

    @property
    def is_empty(self) -> bool:
        return len(self._queue) == 0

    @property
    def tracks(self) -> List[Track]:
        return list(self._queue)

    @property
    def manual_tracks(self) -> List[Track]:
        return [t for t in self._queue if not t.is_autoplay]

    @property
    def autoplay_tracks(self) -> List[Track]:
        return [t for t in self._queue if t.is_autoplay]

    def clear_autoplay(self) -> int:
        """Removes all auto-recommended tracks from queue when user enters new music."""
        remaining = [t for t in self._queue if not t.is_autoplay]
        removed_count = len(self._queue) - len(remaining)
        self._queue = deque(remaining)
        return removed_count

    def add(self, track: Track) -> bool:
        """Adds a single track to the end of the queue."""
        if len(self._queue) >= self.max_size:
            return False
        self._queue.append(track)
        return True

    def extend(self, tracks: List[Track]) -> int:
        """Adds multiple tracks up to max_size. Returns number of tracks added."""
        added = 0
        for track in tracks:
            if len(self._queue) >= self.max_size:
                break
            self._queue.append(track)
            added += 1
        return added

    def pop_next(self) -> Optional[Track]:
        """
        Retrieves the next track taking loop mode into account.
        """
        # If LoopMode is TRACK, replay the current track
        if self.loop_mode == LoopMode.TRACK and self.current_track:
            return self.current_track

        # If LoopMode is QUEUE and there was a current track, add it back to end
        if self.loop_mode == LoopMode.QUEUE and self.current_track:
            self._queue.append(self.current_track)

        # Record into history & played IDs
        if self.current_track:
            self.history.append(self.current_track)
            if self.current_track.video_id:
                self.played_video_ids.add(self.current_track.video_id)
            if len(self.history) > 50:
                self.history.pop(0)

        if not self._queue:
            self.current_track = None
            return None

        self.current_track = self._queue.popleft()
        if self.current_track.video_id:
            self.played_video_ids.add(self.current_track.video_id)
        return self.current_track

    def shuffle(self) -> None:
        """Randomizes the order of tracks currently in queue."""
        tracks = list(self._queue)
        random.shuffle(tracks)
        self._queue = deque(tracks)

    def remove(self, index: int) -> Optional[Track]:
        """Removes a track at 1-based index."""
        if 1 <= index <= len(self._queue):
            tracks = list(self._queue)
            removed = tracks.pop(index - 1)
            self._queue = deque(tracks)
            return removed
        return None

    def clear(self) -> int:
        """Empties the upcoming queue. Returns number of removed items."""
        count = len(self._queue)
        self._queue.clear()
        return count

    def set_loop_mode(self, mode: LoopMode) -> LoopMode:
        self.loop_mode = mode
        return self.loop_mode

    def toggle_loop(self) -> LoopMode:
        """Cycles through LoopMode.OFF -> LoopMode.TRACK -> LoopMode.QUEUE -> LoopMode.OFF"""
        if self.loop_mode == LoopMode.OFF:
            self.loop_mode = LoopMode.TRACK
        elif self.loop_mode == LoopMode.TRACK:
            self.loop_mode = LoopMode.QUEUE
        else:
            self.loop_mode = LoopMode.OFF
        return self.loop_mode

    @property
    def total_duration(self) -> int:
        return sum(t.duration for t in self._queue if t.duration > 0)

    @property
    def formatted_total_duration(self) -> str:
        total = self.total_duration
        if total <= 0:
            return "0s"
        minutes, seconds = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        return f"{minutes}m {seconds}s"

    def get_page(self, page: int = 1, page_size: int = 10) -> Tuple[List[Track], int, int]:
        """
        Returns (tracks_for_page, total_pages, current_page).
        """
        total_items = len(self._queue)
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        tracks_slice = list(self._queue)[start_idx:end_idx]

        return tracks_slice, total_pages, page
