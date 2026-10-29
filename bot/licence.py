"""
Licence module: the bot needs a key, the same keys as SaveX and GalleryX (from KEY_PAGE).

Entering a key activates it with the key server, which answers with a licence it has signed. The
licence is checked here with PUBLIC_KEY (ECDSA P-256), is tied to this copy of the bot (a random
install id kept in data/licence.json), and works offline until it expires (30 days). It's renewed
about once a day, which is also how a revoked key stops the bot.

Only the public half of the signing key is here: the private half never leaves the key server, so a
licence can't be made or edited without it, and one copied from another install is refused.
"""

import base64
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.serialization import load_der_public_key

logger = logging.getLogger("AudioBot.Licence")

# ---- the same values as SaveX (src/lib/license.js) and GalleryX (Licence.kt) ----------------------
LICENSE_SERVER = "https://keys.xo.st"
KEY_PAGE = "https://xo.st/keys/"
PUBLIC_KEY = "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE6v84QGnkymXY/ake/SWzcq2zv3LzlhxmHVj+9ycYkpjyx+7bvq19t+VD2K6eAfSYd3fIJzj0Yj0halDl7S6AVQ=="
# ---------------------------------------------------------------------------------------------------

# Renewed when less than this much of the licence is left (or at most once a day otherwise).
RENEW_WHEN_LEFT = 20 * 86400
RENEW_EVERY = 86400

STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "licence.json"

# What the key server's codes mean for the bot (its own messages talk about browsers).
MESSAGES = {
    "unknown": "That key isn't right. Check it, or get one from " + KEY_PAGE,
    "revoked": "That key has been turned off.",
    "expired": "That key has expired.",
    "too-many": "That key is already in use in as many places as it can be. Remove it from one of them first "
                "(for another copy of this bot: python main.py --remove-key).",
    "not-active": "This bot isn't on that key any more. Enter the key again.",
}
LOCKING_CODES = ("revoked", "expired", "not-active", "unknown")

_current: Optional[dict] = None  # the checked licence's contents, or None


class LicenceError(Exception):
    def __init__(self, message: str, code: Optional[str] = None, offline: bool = False):
        super().__init__(message)
        self.code = code
        self.offline = offline


# ---------------------------------------------------------------- stored state

def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def _install_id() -> str:
    state = _load_state()
    if not state.get("install"):
        state["install"] = secrets.token_hex(16)
        _save_state(state)
    return state["install"]


# ---------------------------------------------------------------- the signature

def _b64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _check(licence) -> Optional[dict]:
    """The licence's contents if it's signed by the key server, for this install, and not expired."""
    if not isinstance(licence, str):
        return None
    try:
        body, sig = licence.split(".")
        raw = _b64url(sig)
        if len(raw) != 64:
            return None
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        key = load_der_public_key(base64.b64decode(PUBLIC_KEY))
        key.verify(der, body.encode("ascii"), ec.ECDSA(hashes.SHA256()))
        p = json.loads(_b64url(body))
    except (ValueError, InvalidSignature, TypeError):
        return None
    if p.get("v") == 1 and p.get("install") == _install_id() and p.get("exp", 0) > time.time():
        return p
    return None


# ---------------------------------------------------------------- the key server

def _call(path: str, data: dict) -> dict:
    req = urllib.request.Request(
        LICENSE_SERVER + path,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "AudioBot-Licence/1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read() or b"{}")
        except ValueError:
            j = {}
        code = j.get("code")
        raise LicenceError(MESSAGES.get(code) or j.get("error") or f"The key server answered with an error ({e.code}).", code)
    except (urllib.error.URLError, OSError, ValueError):
        raise LicenceError("The key server can't be reached. Check your connection and try again.", offline=True)


# ---------------------------------------------------------------- what the bot uses

def load() -> bool:
    """Reads and checks the stored licence (at start)."""
    global _current
    _current = _check(_load_state().get("licence"))
    return licensed()


def licensed() -> bool:
    """The bot may be used: a valid licence, not yet expired."""
    return _current is not None and _current["exp"] > time.time()


def status() -> dict:
    return {
        "licensed": licensed(),
        "tier": _current.get("tier") if _current else None,
        "key_end": _current.get("key") if _current else None,
        "until": _current.get("exp") if _current else None,
    }


def stored_key() -> Optional[str]:
    return _load_state().get("key")


def credentials():
    """(key, install id): what the music service needs to know this bot has a key."""
    return stored_key(), _install_id()


def activate(key: str) -> dict:
    """Activates [key] for this bot. Raises LicenceError."""
    global _current
    key = str(key or "").strip().upper()
    r = _call("/v1/activate", {"key": key, "install": _install_id()})
    p = _check(r.get("licence"))
    if not p:
        raise LicenceError("The key server's answer couldn't be checked. Is this the right bot for that website?")
    state = _load_state()
    state.update(key=key, licence=r["licence"], checked_at=time.time())
    _save_state(state)
    _current = p
    return status()


def renew_if_due(force: bool = False) -> dict:
    """
    Renews the licence when it's due. A key the server says is revoked, expired or no longer on this
    bot locks it at once; no connection changes nothing (the licence keeps working until it expires).
    """
    global _current
    state = _load_state()
    if not state.get("key"):
        return status()
    left = _current["exp"] - time.time() if _current else 0
    if not force and _current and left > RENEW_WHEN_LEFT and time.time() - state.get("checked_at", 0) < RENEW_EVERY:
        return status()
    try:
        r = _call("/v1/check", {"key": state["key"], "install": _install_id()})
    except LicenceError as e:
        if e.offline:
            return status()
        if e.code in LOCKING_CODES:
            for k in ("key", "licence", "checked_at"):
                state.pop(k, None)
            _save_state(state)
            _current = None
        logger.warning(f"Licence check: {e}")
        return {**status(), "error": str(e)}
    p = _check(r.get("licence"))
    if p:
        state.update(licence=r["licence"], checked_at=time.time())
        _save_state(state)
        _current = p
    return status()


def deactivate() -> None:
    """Takes the key off this bot (and frees its place on the key, so it can be used elsewhere)."""
    global _current
    state = _load_state()
    if state.get("key"):
        try:
            _call("/v1/deactivate", {"key": state["key"], "install": _install_id()})
        except LicenceError as e:
            logger.warning(f"Couldn't tell the key server: {e}")
    for k in ("key", "licence", "checked_at"):
        state.pop(k, None)
    _save_state(state)
    _current = None
