# 🎵 Discord Audio Bot

A modern, high-performance Discord music bot supporting **YouTube**, **YouTube Music**, **Spotify**, and **SoundCloud**, equipped with built-in **AdBlock**, **SponsorBlock** (auto-skipping sponsors, intros, and filler), interactive **Search Dropdowns**, continuous **Autoplay Radio** that dynamically queues similar tracks, and a **minimalist, clean UI**.

---

## ⚡ Features

- **Multi-Platform Support**: Stream from YouTube, YouTube Music channels/playlists, Spotify (tracks, albums, playlists), and SoundCloud.
- **SponsorBlock Integration**: Automatically cuts out sponsors, promotional segments, intros, outros, and music video off-topic skits using Ajay's SponsorBlock API and dynamic FFmpeg stream filters.
- **Continuous Autoplay Radio**: When you play a song, the bot dynamically discovers and randomizes a queue of similar tracks using YouTube Radio mixes and smart search expansion—playback never stops unless you stop it.
- **Interactive Search (`/search`)**: Search for any artist or track and select from an interactive dropdown menu with thumbnail previews.
- **Minimalist, Clean UI**: No giant, cluttered embed cards. Features a clean dark-slate theme (`#2B2D31`), a live audio scrubber bar (`0:45 ━━●────── 3:20`), and icon-only interactive controls (`⏸️`, `⏭️`, `⏹️`, `🔁`, `📻`, `📜`).
- **Channel & Playlist Fast-Unpack**: Uses lazy, flat metadata extraction to join voice channels instantly without 60-second timeouts, even on massive YouTube channel tabs (`@Artist`) while automatically filtering out vertical Shorts.
- **Auto-Leave Watchdog**: Automatically disconnects when the voice channel is empty or playback has been idle for 3 minutes.

---

## ❓ Can the bot join Personal Calls / DMs?

**Short answer: No, due to Discord API architecture.**

Discord bots are restricted by the official Discord Developer Platform:
- Bots can only connect to voice channels located within **Discord Servers (Guilds)**.
- **1-on-1 direct calls** and **Group DMs** do not permit bot voice client connections.

**Recommended Solution**:
Create a free, private personal Discord server just for you (and your friends). You can join your own private voice channel and have the bot join you anytime!

---

## 🚀 Quick Start

### 1. Requirements
- **Python 3.10+** (Python 3.12 is recommended)
- **FFmpeg** (Already detected automatically on your system)
- A **Discord Bot Token** from the [Discord Developer Portal](https://discord.com/developers/applications)

### 2. Get a Key
The bot needs a key to run: the same key that unlocks SaveX and GalleryX. Get yours at **https://xo.st/keys/**,
then put it in `.env` (or paste it when the bot asks on first start):
```env
LICENSE_KEY=SAVEX-XXXXX-XXXXX-XXXXX-XXXXX
```
Searching, links, Spotify, autoplay radio and SponsorBlock go through the music service at `api.xo.st`, which
only answers bots with a valid key, so the bot needs an internet connection (it needs one for Discord anyway). To move the key to another computer, run `python main.py --remove-key` on the old one first.

### 3. Configure Token
Open `.env` in the bot directory and paste your bot token:
```env
DISCORD_TOKEN=your_bot_token_here
```

Spotify links (tracks, albums and playlists) work out of the box: no Spotify credentials needed.

### 4. Launch
On **Windows**:
Double-click `run.bat` or open PowerShell in the project directory and run:
```powershell
.\.venv\Scripts\python.exe main.py
```

On **Linux / macOS**:
```bash
chmod +x run.sh
./run.sh
```

---

## 🎮 Commands

Both Slash Commands (`/command`) and Classic Prefix Commands (`!command`) are supported:

| Command | Description |
| :--- | :--- |
| `/play <query>` | Play a song, URL, channel, or playlist (YouTube, Spotify, SoundCloud) |
| `/search <query>` | Search by name and choose from an interactive dropdown list |
| `/nowplaying` | Show the minimal now playing card with scrubber and control buttons |
| `/queue [page]` | View the upcoming song queue |
| `/pause` | Pause playback |
| `/resume` | Resume playback |
| `/skip` | Skip the current song |
| `/stop` | Stop playback and clear the queue |
| `/seek <position>` | Seek to a specific timestamp (e.g. `1:30` or `90`) |
| `/shuffle` | Randomize the upcoming queue |
| `/loop <off\|track\|queue>` | Toggle loop between off, current song, or entire queue |
| `/clear` | Remove all songs from the upcoming queue |
| `/remove <#>` | Remove a specific song by its queue number |
| `/volume <1-150>` | Adjust playback volume |
| `/autoplay` | Toggle continuous similar-content radio on or off |
| `/sponsorblock` | Toggle or configure SponsorBlock skipping |
| `/leave` | Disconnect the bot from voice |
| `/ping` | Check WebSocket gateway and voice connection latency |
| `/help` | Show command reference guide |

---

## 🛡️ SponsorBlock Categories

The bot automatically skips the following segment types by default:
- `sponsor` — Sponsored promotions and product plugs
- `selfpromo` — Self-promotion, merchandise, subscriber pitches
- `interaction` — "Like and subscribe" reminders
- `intro` — Intro animations or logo bumpers
- `outro` — Credits and end-screens
- `music_offtopic` — Non-music intro skits or dialog in music videos
