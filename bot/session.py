"""
Saved sessions: what each server was listening to (the track and where in it, the queue, loop, volume,
radio and SponsorBlock settings, and the channels), kept in data/sessions.json. Written every few seconds
and when the bot shuts down, so after a restart or an update it rejoins and carries on where it was.
"""

import json
import logging
import os
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional

from bot.audio_source import Track
from bot.queue_manager import LoopMode

logger = logging.getLogger("AudioBot.Session")

SESSIONS_FILE = Path(__file__).resolve().parent.parent / "data" / "sessions.json"
MAX_AGE = 24 * 3600          # a session older than this (the bot was off for a day) isn't picked up again

def _track_to_dict(t: Track) -> Dict[str, Any]:
    return {
        "title": t.title, "webpage_url": t.webpage_url, "duration": t.duration, "thumbnail": t.thumbnail,
        "uploader": t.uploader, "video_id": t.video_id, "source_type": t.source_type,
        "search_query": t.search_query, "is_autoplay": t.is_autoplay,
        "requester": t.requester.id if t.requester else None,
    }


def _track_from_dict(d: Dict[str, Any], guild) -> Track:
    requester = guild.get_member(d["requester"]) if d.get("requester") else None
    return Track.from_brain(d, requester=requester, is_autoplay=bool(d.get("is_autoplay")))


def snapshot(player) -> Optional[Dict[str, Any]]:
    """What [player] is doing, or None when there's nothing worth picking up again."""
    vc = player.voice_client
    if not vc or not vc.is_connected() or not vc.channel:
        return None
    current = player.current_track
    if not current and player.queue.is_empty:
        return None
    return {
        "voice": vc.channel.id,
        "text": getattr(player.last_bound_channel, "id", None),
        "now_playing": player.now_playing_message.id if player.now_playing_message else None,
        "current": _track_to_dict(current) if current else None,
        "position": round(player.playback_position, 1),
        "paused": player.is_paused,
        "queue": [_track_to_dict(t) for t in player.queue.tracks],
        "loop": player.queue.loop_mode.value,
        "volume": player.volume,
        "autoplay": player.autoplay_enabled,
        "sponsorblock": player.sponsorblock_enabled,
        "categories": list(player.sponsor_categories),
        "played": list(player.queue.played_video_ids)[-500:],
        "saved_at": time.time(),
    }


def save_all(players) -> None:
    """Writes the sessions of [players] (replacing the file; servers with nothing playing drop out)."""
    data = {}
    for p in players:
        try:
            snap = snapshot(p)
        except Exception as e:
            logger.debug(f"Couldn't snapshot guild {p.guild.id}: {e}")
            continue
        if snap:
            data[str(p.guild.id)] = snap
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SESSIONS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, SESSIONS_FILE)


def load_all() -> Dict[int, Dict[str, Any]]:
    """The saved sessions that are recent enough to pick up again."""
    try:
        data = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    now = time.time()
    return {int(g): s for g, s in data.items() if now - s.get("saved_at", 0) < MAX_AGE}


def restore_into(player, s: Dict[str, Any]) -> Optional[Track]:
    """Puts saved session [s] back into [player]. Returns the track to start with (or None)."""
    guild = player.guild
    player.volume = int(s.get("volume", player.volume))
    player.autoplay_enabled = bool(s.get("autoplay", player.autoplay_enabled))
    player.sponsorblock_enabled = bool(s.get("sponsorblock", player.sponsorblock_enabled))
    player.sponsor_categories = list(s.get("categories") or player.sponsor_categories)
    try:
        player.queue.loop_mode = LoopMode(s.get("loop", "off"))
    except ValueError:
        pass
    player.queue.played_video_ids = set(s.get("played") or [])
    tracks = [_track_from_dict(d, guild) for d in s.get("queue") or []]
    current = _track_from_dict(s["current"], guild) if s.get("current") else None
    if current:
        tracks.insert(0, current)
    player.queue._queue = deque(tracks)
    player.queue.current_track = None
    return current or (tracks[0] if tracks else None)
