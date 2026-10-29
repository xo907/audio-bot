"""
24/7 mode: servers where the bot stays in its voice channel instead of leaving when idle or alone.
Kept in data/stay.json ({guild id: voice channel id}), so the bot rejoins after a restart or a dropped
connection. Turned on and off with /stay; /leave turns it off.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("AudioBot.Stay")

STAY_FILE = Path(__file__).resolve().parent.parent / "data" / "stay.json"

_channels: Optional[Dict[str, int]] = None


def _load() -> Dict[str, int]:
    global _channels
    if _channels is None:
        try:
            _channels = {str(k): int(v) for k, v in json.loads(STAY_FILE.read_text(encoding="utf-8")).items()}
        except (OSError, ValueError, AttributeError):
            _channels = {}
    return _channels


def _save() -> None:
    STAY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STAY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_load(), indent=2), encoding="utf-8")
    os.replace(tmp, STAY_FILE)


def channel_for(guild_id: int) -> Optional[int]:
    """The voice channel the bot stays in on this server, or None when 24/7 mode is off."""
    return _load().get(str(guild_id))


def enable(guild_id: int, channel_id: int) -> None:
    _load()[str(guild_id)] = channel_id
    _save()


def disable(guild_id: int) -> bool:
    """Turns 24/7 mode off. Returns whether it was on."""
    was_on = _load().pop(str(guild_id), None) is not None
    if was_on:
        _save()
    return was_on


def all_channels() -> Dict[int, int]:
    return {int(g): c for g, c in _load().items()}
