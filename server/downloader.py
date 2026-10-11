import asyncio
import os
import sys
import subprocess
import traceback
from urllib.parse import urlparse, urlunparse
from pathlib import Path
from typing import Optional, List
from server.db import upsert_task, add_song, song_exists_by_filename
from server.audio_utils import extract_metadata

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".aac"}

def clean_spotify_url(url: str) -> str:
    """Strips tracking query params from spotify URLs for clean downloading"""
    if "open.spotify.com" in url:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return url

def _run_spotdl_process(cmd: list, cwd: Path):
    """Runs spotdl in standard synchronous subprocess with PATH containing deno and ffmpeg"""
    env = os.environ.copy()
    from spotdl.utils.config import get_spotdl_path
    try:
        spotdl_path = str(get_spotdl_path().absolute())
        env["PATH"] = f"{spotdl_path}{os.pathsep}{env.get('PATH', '')}"
    except Exception:
        pass

    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        env=env
    )

def scan_and_index_directory(songs_dir: Path, covers_dir: Path) -> int:
    """
    Scans songs directory and indexes any unindexed audio files into the database.
    If Telegram cloud is configured, uploads to Telegram and removes local file.
    """
    songs_dir.mkdir(parents=True, exist_ok=True)
    covers_dir.mkdir(parents=True, exist_ok=True)
    indexed_count = 0

    for file_path in songs_dir.glob("*.*"):
        if file_path.suffix.lower() in AUDIO_EXTENSIONS:
            if not song_exists_by_filename(file_path.name):
                try:
                    title, artist, album, duration, cover_fn = extract_metadata(file_path, covers_dir)
                    filesize = file_path.stat().st_size

                    # Check Telegram Cloud storage
                    from server.telegram_storage import upload_audio_to_telegram, get_telegram_config
                    tg_cfg = get_telegram_config()
                    tg_file_id = None
                    if tg_cfg.get("bot_token") and tg_cfg.get("chat_id"):
                        tg_file_id = upload_audio_to_telegram(file_path, title, artist, int(duration))
                        if tg_file_id:
                            # Remove file from disk immediately! 0 bytes on PC!
                            try:
                                file_path.unlink()
                            except Exception:
                                pass

                    add_song(
                        title=title or file_path.stem,
                        artist=artist or "Unknown Artist",
                        album=album or "Unknown Album",
                        duration=duration,
                        filename=file_path.name,
                        cover_filename=cover_fn,
                        filesize=filesize,
                        source="telegram" if tg_file_id else "spotdl",
                        telegram_file_id=tg_file_id
                    )
                    indexed_count += 1
                except Exception as e:
                    print(f"Failed to index {file_path.name}: {e}")

    return indexed_count

async def run_spotdl_download(task_id: str, raw_query: str, output_dir: Path, covers_dir: Path):
    """
    Runs spotDL download in background and indexes resulting files into DB.
    """
    clean_query = clean_spotify_url(raw_query.strip())
    upsert_task(task_id, clean_query, "downloading", "Downloading song from Spotify / YouTube...")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    covers_dir.mkdir(parents=True, exist_ok=True)

    # Execute spotdl inside output_dir with fallback providers and output template
    cmd = [
        sys.executable,
        "-m",
        "spotdl",
        "download",
        clean_query,
        "--output",
        "{artist} - {title}.{output-ext}",
        "--audio",
        "soundcloud",
        "youtube",
        "bandcamp",
        "youtube-music",
    ]

    try:
        result = await asyncio.to_thread(_run_spotdl_process, cmd, output_dir)
        out_text = result.stdout or ""
        err_text = result.stderr or ""
        combined_logs = (out_text + "\n" + err_text).strip()

        # Check for FFmpeg error
        if "ffmpeg is not installed" in combined_logs.lower():
            upsert_task(
                task_id,
                clean_query,
                "failed",
                "FFmpeg missing",
                "FFmpeg is not installed. Please run 'uv run spotdl --download-ffmpeg' in your terminal."
            )
            return

        # Scan and index audio files
        newly_indexed = scan_and_index_directory(output_dir, covers_dir)

        if newly_indexed > 0:
            upsert_task(
                task_id,
                clean_query,
                "completed",
                f"Successfully added {newly_indexed} track(s) to library!",
                ""
            )
        else:
            # If 0 songs were added, spotdl did not produce an audio file
            error_details = combined_logs[-400:] if combined_logs else f"Exit code {result.returncode} (No audio file produced)"
            upsert_task(
                task_id,
                clean_query,
                "failed",
                "0 songs downloaded",
                error_details
            )

    except Exception as e:
        upsert_task(task_id, clean_query, "failed", "Error occurred", f"{type(e).__name__}: {e}")
