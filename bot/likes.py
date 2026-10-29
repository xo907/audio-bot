"""
Liked songs: the ❤️ button on the player card. Each person's likes are kept in data/likes.json
({user id: [track, newest last]}), so the card can show who liked the song playing and /liked can show
anyone's liked songs (and queue them).
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

LIKES_FILE = Path(__file__).resolve().parent.parent / "data" / "likes.json"
MAX_PER_USER = 1000

_users: Optional[Dict[str, List[Dict[str, Any]]]] = None


def _load() -> Dict[str, List[Dict[str, Any]]]:
    global _users
    if _users is None:
        try:
            _users = json.loads(LIKES_FILE.read_text(encoding="utf-8"))
            if not isinstance(_users, dict):
                _users = {}
        except (OSError, ValueError):
            _users = {}
    return _users


def _save() -> None:
    LIKES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LIKES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_load(), indent=1), encoding="utf-8")
    os.replace(tmp, LIKES_FILE)


def key_of(track) -> str:
    """What makes two tracks the same song: the YouTube video, or else the link."""
    return f"yt:{track.video_id}" if track.video_id else track.webpage_url


def _key_of_saved(d: Dict[str, Any]) -> str:
    return f"yt:{d['video_id']}" if d.get("video_id") else d["webpage_url"]


def is_liked(user_id: int, track) -> bool:
    k = key_of(track)
    return any(_key_of_saved(d) == k for d in _load().get(str(user_id), []))


def toggle(user_id: int, track) -> bool:
    """Likes [track] for [user_id], or takes the like back. Returns whether it's liked now."""
    k = key_of(track)
    mine = _load().setdefault(str(user_id), [])
    kept = [d for d in mine if _key_of_saved(d) != k]
    liked = len(kept) == len(mine)
    if liked:
        kept.append({
            "title": track.title, "webpage_url": track.webpage_url, "duration": track.duration,
            "thumbnail": track.thumbnail, "uploader": track.uploader, "video_id": track.video_id,
            "source_type": track.source_type, "search_query": track.search_query, "liked_at": int(time.time()),
        })
        del kept[:-MAX_PER_USER]
    if kept:
        _load()[str(user_id)] = kept
    else:
        _load().pop(str(user_id), None)
    _save()
    return liked


def likers(track) -> List[int]:
    """Who liked [track], first liker first."""
    k = key_of(track)
    found = []
    for uid, items in _load().items():
        for d in items:
            if _key_of_saved(d) == k:
                found.append((d.get("liked_at", 0), int(uid)))
                break
    return [uid for _, uid in sorted(found)]


def liked_by(user_id: int) -> List[Dict[str, Any]]:
    """[user_id]'s liked songs, newest first."""
    return list(reversed(_load().get(str(user_id), [])))
