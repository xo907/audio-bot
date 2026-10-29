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
- **Picks Up After Restarts**: The song, position, queue and settings are saved every few seconds, so after a restart or an update the bot rejoins and carries on where it was.
- **Clean Chat**: The bot's replies remove themselves after 15 seconds (60 for ones with buttons or menus) and typed `!commands` are removed at once (needs **Manage Messages** for that), so only the live player stays. Turn it off with `CLEAN_CHAT=false` in `.env`.
- **One Channel Only**: `/channel` limits the bot to the channel it's used in (for people who can manage the server).
- **Auto-Leave Watchdog**: Automatically disconnects when the voice channel is empty or playback has been idle for 3 minutes, unless **24/7 mode** (`/stay`) is on: then it stays in its channel and rejoins after restarts or dropped connections.

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

You need:
- A **Discord bot token** from the [Discord Developer Portal](https://discord.com/developers/applications)
  (Applications › your app › **Bot** › Reset Token). On that same page, turn on **Message Content Intent**.
- A **key** from **https://xo.st/keys/**: the same key that unlocks SaveX and GalleryX.

Searching, links, Spotify, autoplay radio and SponsorBlock go through the music service at `api.xo.st`, which
only answers bots with a valid key. No Spotify credentials are needed on your side.

### 🐧 Linux

**1. Install Python, FFmpeg, Opus and Git**

> Logged in as `root` with no `sudo` (common on a VPS, where you get `sudo: command not found`)? Run this
> first, and every command below then works as written:
> ```bash
> apt update && apt install -y sudo
> ```

Debian / Ubuntu:
```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip ffmpeg libopus0 git
```

Fedora:
```bash
sudo dnf install -y python3 python3-pip ffmpeg-free opus git
```

Arch:
```bash
sudo pacman -S --needed python python-pip ffmpeg opus git
```

**2. Download the bot**
```bash
git clone https://github.com/xo907/audio-bot.git && cd audio-bot
```

**3. Install its packages**
```bash
python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements.txt
```

**4. Add your token and key**

Replace `PASTE_YOUR_TOKEN_HERE` and `PASTE_YOUR_KEY_HERE` in this command with your own, then run it:
```bash
cp .env.example .env && sed -i -e 's|^DISCORD_TOKEN=.*|DISCORD_TOKEN=PASTE_YOUR_TOKEN_HERE|' -e 's|^LICENSE_KEY=.*|LICENSE_KEY=PASTE_YOUR_KEY_HERE|' .env
```
(Or open it in an editor: `nano .env`. The other settings in it are optional.)

**5. Start it**
```bash
.venv/bin/python main.py
```
You should see `Licence OK` or `Key activated`, then `Logged in as: …`. Press `Ctrl+C` to stop it.

**6. Invite it to your server**

In the Developer Portal: your app › **OAuth2** › URL Generator. Tick `bot` and `applications.commands`, then
under Bot Permissions tick `View Channels`, `Send Messages`, `Embed Links`, `Connect` and `Speak`. Open the
generated link and pick your server.

#### Keep it running (optional)

To run the bot in the background, start it when the computer boots, and restart it if it crashes, run these
**from inside the `audio-bot` folder**:
```bash
sudo tee /etc/systemd/system/audio-bot.service > /dev/null <<EOF
[Unit]
Description=Discord Audio Bot
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$PWD
ExecStart=$PWD/.venv/bin/python main.py
Restart=on-failure
RestartSec=10
RestartPreventExitStatus=2

[Install]
WantedBy=multi-user.target
EOF
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now audio-bot
```

Check on it, watch its log, or restart it:
```bash
systemctl status audio-bot
```
```bash
journalctl -u audio-bot -f
```
```bash
sudo systemctl restart audio-bot
```

#### Update to the latest version
```bash
git pull && .venv/bin/pip install -r requirements.txt && sudo systemctl restart audio-bot
```
(Leave out `&& sudo systemctl restart audio-bot` if you didn't set up the service.)

#### Move the key to another computer
Each key works in a limited number of places. Free this one up first:
```bash
.venv/bin/python main.py --remove-key
```

### 🪟 Windows

Install [Python 3.10+](https://www.python.org/) (tick "Add Python to PATH") and FFmpeg (`winget install ffmpeg`),
download the bot, then double-click `run.bat`. It sets everything up, creates `.env`, and asks for your key the
first time. Put your bot token in `.env` as `DISCORD_TOKEN=…`.

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
| `/channel` | Only work in this channel; use it there again to work everywhere (Manage Server) |
| `/stay` | 24/7 mode: stay in the voice channel and never leave, even after restarts (toggle) |
| `/leave` | Disconnect the bot from voice (also turns 24/7 mode off) |
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
