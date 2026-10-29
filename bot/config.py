"""
Configuration module for the Discord Audio Bot.
Loads environment variables and resolves dependencies like FFmpeg.
"""

import os
import shutil
import glob
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


def resolve_ffmpeg_path() -> str:
    """
    Intelligently locates the FFmpeg executable across PATH,
    WinGet installations, local project folders, and environment overrides.
    """
    # 1. User-specified override
    custom_path = os.getenv("FFMPEG_PATH", "").strip()
    if custom_path and Path(custom_path).is_file():
        return custom_path

    # 2. System PATH check
    which_ffmpeg = shutil.which("ffmpeg")
    if which_ffmpeg:
        return which_ffmpeg

    # 3. Check Windows WinGet standard link location
    local_app_data = os.getenv("LOCALAPPDATA", "")
    if local_app_data:
        winget_link = Path(local_app_data) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
        if winget_link.is_file():
            return str(winget_link)

        # 4. Search WinGet installed packages directory
        winget_pkg_pattern = str(Path(local_app_data) / "Microsoft" / "WinGet" / "Packages" / "*FFmpeg*" / "**" / "ffmpeg.exe")
        matches = glob.glob(winget_pkg_pattern, recursive=True)
        if matches:
            return matches[0]

    # 5. Local project binaries
    local_bin = Path(__file__).resolve().parent.parent / "bin" / "ffmpeg.exe"
    if local_bin.is_file():
        return str(local_bin)

    local_exe = Path(__file__).resolve().parent.parent / "ffmpeg.exe"
    if local_exe.is_file():
        return str(local_exe)

    # Fallback to standard command name
    return "ffmpeg"


# Bot Settings
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!").strip()
DEFAULT_VOLUME = int(os.getenv("DEFAULT_VOLUME", 100))
MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", 500))
INACTIVITY_TIMEOUT = int(os.getenv("INACTIVITY_TIMEOUT", 180))  # 3 minutes

# Clean chat: the bot's replies remove themselves after CLEAN_CHAT_DELAY seconds (ones with buttons or
# menus after CLEAN_CHAT_MENU_DELAY), typed !commands are removed at once; the live player card stays.
CLEAN_CHAT = os.getenv("CLEAN_CHAT", "true").lower() in ("true", "1", "yes")
CLEAN_CHAT_DELAY = float(os.getenv("CLEAN_CHAT_DELAY", 15))
CLEAN_CHAT_MENU_DELAY = float(os.getenv("CLEAN_CHAT_MENU_DELAY", 60))

# Music service (search, links, Spotify, radio, SponsorBlock)
BRAIN_URL = os.getenv("BRAIN_URL", "https://api.xo.st").strip().rstrip("/")

# FFmpeg Executable Path
FFMPEG_EXECUTABLE = resolve_ffmpeg_path()

# SponsorBlock Settings
SPONSORBLOCK_ENABLED_DEFAULT = os.getenv("SPONSORBLOCK_ENABLED", "true").lower() in ("true", "1", "yes")
_raw_categories = os.getenv("SPONSORBLOCK_CATEGORIES", "sponsor,selfpromo,interaction,intro,outro,music_offtopic")
DEFAULT_SPONSOR_CATEGORIES = [c.strip().lower() for c in _raw_categories.split(",") if c.strip()]
VALID_SPONSOR_CATEGORIES = [
    "sponsor",
    "selfpromo",
    "interaction",
    "intro",
    "outro",
    "music_offtopic",
    "preview",
    "filler",
]

# Autoplay / Radio Recommendation Settings
AUTOPLAY_DEFAULT = os.getenv("AUTOPLAY_DEFAULT", "true").lower() in ("true", "1", "yes")
AUTOPLAY_BATCH_SIZE = int(os.getenv("AUTOPLAY_BATCH_SIZE", 5))
