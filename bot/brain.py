"""
Brain client: the music service at BRAIN_URL that turns searches, links, Spotify links and radio seeds
into tracks, and works out SponsorBlock skips. Every call carries this bot's key, so it only answers a
bot with a valid key. Playback itself (the audio stream) stays on this bot.
"""

import logging
from typing import Any, Dict, Optional

import aiohttp

from bot import licence
from bot.config import BRAIN_URL

logger = logging.getLogger("AudioBot.Brain")

_session: Optional[aiohttp.ClientSession] = None


class BrainError(RuntimeError):
    pass


async def call(path: str, data: Dict[str, Any], timeout: float = 60.0) -> Dict[str, Any]:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(headers={"User-Agent": "AudioBot/1.1"})
    key, install = licence.credentials()
    headers = {"X-Licence-Key": key or "", "X-Install": install}
    try:
        async with _session.post(BRAIN_URL + path, json=data, headers=headers,
                                 timeout=aiohttp.ClientTimeout(total=timeout)) as res:
            body = await res.json(content_type=None)
            status = res.status
    except Exception as e:
        logger.warning(f"Music service unreachable ({path}): {e}")
        raise BrainError("The music service can't be reached right now. Try again in a moment.")
    if status != 200:
        message = (body or {}).get("error") or f"The music service answered with an error ({status})."
        if (body or {}).get("code") == "licence":
            message += f" Keys come from {licence.KEY_PAGE}"
        raise BrainError(message)
    return body or {}


async def close() -> None:
    if _session and not _session.closed:
        await _session.close()
