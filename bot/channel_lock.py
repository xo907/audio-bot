"""
One channel only: servers where the bot answers commands in a single text channel. Kept in
data/channel.json ({guild id: text channel id}). Set and lifted with /channel (Manage Server).
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional

LOCK_FILE = Path(__file__).resolve().parent.parent / "data" / "channel.json"

_channels: Optional[Dict[str, int]] = None


def _load() -> Dict[str, int]:
    global _channels
    if _channels is None:
        try:
            _channels = {str(k): int(v) for k, v in json.loads(LOCK_FILE.read_text(encoding="utf-8")).items()}
        except (OSError, ValueError, AttributeError):
            _channels = {}
    return _channels


def _save() -> None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOCK_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_load(), indent=2), encoding="utf-8")
    os.replace(tmp, LOCK_FILE)


def channel_for(guild_id: int) -> Optional[int]:
    """The only text channel the bot works in on this server, or None when it works everywhere."""
    return _load().get(str(guild_id))


def allowed(guild_id: Optional[int], channel_id: Optional[int]) -> bool:
    locked = channel_for(guild_id) if guild_id else None
    return not locked or locked == channel_id


def lock(guild_id: int, channel_id: int) -> None:
    _load()[str(guild_id)] = channel_id
    _save()


def unlock(guild_id: int) -> bool:
    was = _load().pop(str(guild_id), None) is not None
    if was:
        _save()
    return was
