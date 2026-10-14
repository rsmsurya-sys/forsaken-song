
<!--- mdformat-toc start --slug=github --->

<!---
!!! IF EDITING THE README, MOST CHANGES SHOULD ALSO BE PROPAGATED TO index.md in `/docs/`.
!!! ADJUST FORMATTING THERE AS NEEDED, AND REMOVE README-ONLY / ReadTheDocs REFERENCES.
--->

# FORSAKEN SONG 2.0 — Next-Generation Music OS ⚡
> **"Music That Understands You."**  
> An AI-powered music streaming platform and acoustic intelligence OS that understands your mood, listening habits, surroundings, and energy level.

---

## 🚀 Advanced Features Built into FORSAKEN SONG 2.0

### 1. AI Mood Engine 🧠
- **Emotional Intent & Resonance Scoring**: Natural language mood extraction (Sad, Energetic, Chill, Focus, Happy, Nocturnal).
- **Directional Frequency Shifting**: Users choose between:
  - **"Stay in My Mood"**: Harmonic alignment matching your exact emotional state.
  - **"Help Me Feel Better"**: Dynamic acoustic elevation moving you toward calming or uplifting frequencies.

### 2. Forsaken Time Machine ⏳
- **Forgotten Gems Radar**: Surfaces long-neglected songs in your vault waiting to be rediscovered.
- **Top Loop Telemetry**: Displays all-time most replayed tracks with total loop counters.
- **AI Music Memory**: Analyzes time-of-day listening patterns (e.g. Midnight Pulse vs Dawn Ascent) and provides revival alerts.

### 3. AI Music DNA 🧬
- **Dynamic Acoustic Profile**: Calculates Energy Score, Discovery Index, Repeat Ratio, and Tempo Preferences (BPM).
- **Language Distribution Matrix**: Tracks listening ratios across Tamil, English, Hindi, and Global music.
- **Friend Compatibility Matcher**: Interactive acoustic overlap calculation (Genre overlap, Energy sync, Shared cadence).

### 4. Cross-Language Music Bridge 🌍
- Cross-language acoustic similarity matching (e.g., Tamil ↔ Malayalam ↔ Hindi ↔ English).
- Compares vocal cadence, instrumentation, and driving tempo across language barriers without assuming identical lexical meaning.

### 5. AI Listening Rooms & Live Party Sync 🎭
- **Live Room ID Sync (Party Mode)**:
  - **Host Mode**: Create a unique Room ID (e.g. `FK-8921`) and share the code or 1-click link with your friend.
  - **Listener Mode**: Friend enters Room ID or opens link — whatever the host plays, pauses, skips, or scrubs will immediately play in real-time on the friend's device!
  - Powered by low-latency **WebSockets (`/ws/room/{room_code}`)** with auto-reconnect and drift compensation.
- **Deep Focus Sanctum**: Synced study room with live **25/5 interactive Pomodoro Timer**.
- **Atmospheric Sanctuary**: Ambient emotional resonance room for contemplative nocturnal listening.
- **Sonic Battle Arena**: Musical tracks collide with live voting.

### 6. Forsaken Sound Lab 🎛️
- **Real-Time 5-Band Equalizer**: Driven by the browser's native **Web Audio API (`BiquadFilterNodes`)** connected to audio playback (60Hz, 250Hz, 1kHz, 4kHz, 16kHz).
- **AI Natural Language EQ Assistant**: Type requests like *"Make the bass stronger, but keep the vocals clear"* and the AI dynamically adjusts equalizer gain in real-time.

### 7. AI Conversational Discovery 🔎
- Natural language discovery without endless scrolling:
  - *"Find Tamil songs with powerful vocals"*
  - *"Find songs for a 30-minute evening walk"* (calculates cumulative duration to fit your exact time budget)
  - *"Suggest energetic music without heavy bass"*
  - *"Find underrated songs that match my taste"*

### 8. Forsaken Flow ⚡
- **Adaptive Session Progression**: A listening session that intelligently modulates queue and pacing across 4 distinct stages:
  1. **Stage 1 (15%)**: Cognitive Settle-In (Warm melody, gentle acoustic ramp)
  2. **Stage 2 (55%)**: Deep Atmospheric Immersion (Consistent rhythmic pulse, high focus lock)
  3. **Stage 3 (20%)**: Cognitive Stabilization (Stimulation reduction, harmonic soothing)
  4. **Stage 4 (10%)**: Mindful Outro & Return (Ambient resolution, tranquil landing)

---

## 🎨 UI Architecture: "Cyber-Aurora" Studio

- **Color Palette**: Deep Void (`#040914`, `#070d1a`), Electric Aurora Cyan (`#00f2fe`), Neon Emerald (`#00e676`), and Violet Resonance (`#4facfe`).
- **Hero Stage**: Interactive Rotating Vinyl Disc with animated sound ripples that dynamically spins during playback.
- **Floating Island Player**: Capsule bar with glowing neon scrubber and real-time Web Audio integration.
- **Compact Density Mode**: Power-user toggle (`C` key) and floating mini-HUD for high-efficiency listening.

---

## 💻 How to Run FORSAKEN SONG Locally

### Option 1: Quick Launcher (Windows)
Double-click `run_local.bat` in the project root:
```bat
run_local.bat
```

### Option 2: Command Line with uv
```bash
uv run python -m uvicorn server.main:app --port 8000 --reload
```

### App URLs:
- **Desktop Studio (Full Experience)**: `http://localhost:8000/desktop`
- **Mobile Responsive Player**: `http://localhost:8000/mobile`
- **Admin Hub & Telegram Cloud**: `http://localhost:8000/admin`

---

## 📦 Core spotDL Engine (Underlying Downloader)

<div align="center">

# spotDL v4
**spotDL** finds songs from Spotify playlists on YouTube and downloads them - along with album art, lyrics and metadata.
</div>


______________________________________________________________________
**[Read the documentation on ReadTheDocs!](https://spotdl.readthedocs.io)**
______________________________________________________________________

## Installation

Refer to our [Installation Guide](docs/installation.md) for more details.

### Python (Recommended Method)

- _spotDL_ can be installed by running `pip install spotdl`.
- To update spotDL run `pip install --upgrade spotdl`

  > On some systems you might have to change `pip` to `pip3`.

<details>
    <summary style="font-size:1.25em"><strong>Other options</strong></summary>

- Prebuilt executable
  - You can download the latest version from the
    [Releases Tab](https://github.com/spotDL/spotify-downloader/releases)
- On Termux
  - `curl -L https://raw.githubusercontent.com/spotDL/spotify-downloader/master/scripts/termux.sh | sh`
- Arch
  - There is an [Arch User Repository (AUR) package](https://aur.archlinux.org/packages/spotdl/) for
    spotDL.
- Docker
  - Build image:

    ```bash
    docker build -t spotdl .
    ```

  - Launch container with spotDL parameters (see section below). You need to create mapped
    volume to access song files

    ```bash
    docker run --rm -v $(pwd):/music spotdl download [trackUrl]
    ```

  - For Docker Compose and permission-managed Docker downloads, see
    [the Docker section in `/docs/index.md`](docs/index.md#docker).

  - Build from source

    ```bash
    git clone https://github.com/spotDL/spotify-downloader && cd spotify-downloader
    pip install uv
    uv sync
    uv run scripts/build.py
    ```

    An executable is created in `spotify-downloader/dist/`.

</details>

### Installing FFmpeg

FFmpeg is required for spotDL. If using FFmpeg only for spotDL, you can simply install FFmpeg to your spotDL installation directory:
`spotdl --download-ffmpeg`

We recommend the above option, but if you want to install FFmpeg system-wide,
follow these instructions

- [Windows Tutorial](https://windowsloop.com/install-ffmpeg-windows-10/)
- OSX - `brew install ffmpeg`
- Linux - `sudo apt install ffmpeg` or use your distro's package manager

### Installing Deno

We strongly recommend installing Deno. spotDL uses yt-dlp for YouTube downloads, and some
videos require Deno to download successfully. Without Deno, spotDL may fail to download some
songs, including videos marked as "made for kids".

If using Deno only for spotDL, install Deno to your spotDL directory:
`spotdl --download-deno`

If you want to install Deno system-wide instead, follow the
[official Deno installation guide](https://docs.deno.com/runtime/getting_started/installation/).

## Usage

Using SpotDL without options:

```sh
spotdl [urls]
```

You can run _spotDL_ as a package if running it as a script doesn't work:

```sh
python -m spotdl [urls]
```

General usage:

```sh
spotdl [operation] [options] QUERY
```

There are different **operations** spotDL can perform. The _default_ is `download`, which simply downloads the songs from YouTube and embeds metadata.

The **query** for spotDL is usually a list of Spotify URLs, but for some operations like **sync**, only a single link or file is required.
For a list of all **options** use ```spotdl -h```

<details>
<summary style="font-size:1em"><strong>Supported operations</strong></summary>

- `save`: Saves only the metadata from Spotify without downloading anything.
    - Usage:
        `spotdl save [query] --save-file {filename}.spotdl`

- `web`: Starts a web interface instead of using the command line. However, it has limited features and only supports downloading individual songs.

- `url`: Get user-friendly URL for each song from the query.
    - Usage:
        `spotdl url [query]`

- `sync`: Updates directories. Compares the directory with the current state of the playlist. Newly added songs will be downloaded and removed songs will be deleted. No other songs will be downloaded and no other files will be deleted.

    - Usage:
        `spotdl sync [query] --save-file {filename}.spotdl`

        This creates a new **sync** file. To update the directory in the future, use:

        `spotdl sync {filename}.spotdl`

- `meta`: Updates metadata for the provided song files.

</details>

## Music Sourcing and Audio Quality

spotDL uses YouTube as a source for music downloads. This method is used to avoid any issues related to downloading music from Spotify.

> **Note**
> Users are responsible for their actions and potential legal consequences. We do not support unauthorized downloading of copyrighted material and take no responsibility for user actions.

### Audio Quality

spotDL downloads music from YouTube and is designed to always download the highest possible bitrate; which is 128 kbps for regular users and 256 kbps for YouTube Music premium users.

Check the [Audio Formats](docs/usage.md#audio-formats-and-quality) page for more info.

## Contributing

Interested in contributing? Check out our [CONTRIBUTING.md](docs/CONTRIBUTING.md) to find
resources around contributing along with a guide on how to set up a development environment.

### Join our amazing community as a code contributor

<a href="https://github.com/spotDL/spotify-downloader/graphs/contributors">
  <img class="dark-light" src="https://contrib.rocks/image?repo=spotDL/spotify-downloader&anon=0&columns=25&max=100&r=true" />
</a>

## License

This project is Licensed under the [MIT](/LICENSE) License.
