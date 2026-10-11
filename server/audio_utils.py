import os
import uuid
from pathlib import Path
from typing import Tuple, Optional
import mutagen
from mutagen.id3 import ID3, APIC
from mutagen.mp3 import MP3
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover

def extract_metadata(file_path: Path, covers_dir: Path) -> Tuple[str, str, str, float, Optional[str]]:
    """
    Extracts title, artist, album, duration, and cover image from an audio file.
    Returns: (title, artist, album, duration_seconds, cover_filename)
    """
    title = file_path.stem
    artist = "Unknown Artist"
    album = "Unknown Album"
    duration = 0.0
    cover_filename = None

    try:
        audio = mutagen.File(file_path)
        if audio is not None:
            if hasattr(audio, "info") and hasattr(audio.info, "length"):
                duration = round(float(audio.info.length), 2)

            # Try common tag keys across formats
            # 1. MP3 ID3 tags
            if isinstance(audio, MP3) or (hasattr(audio, "tags") and isinstance(audio.tags, ID3)):
                tags = audio.tags
                if tags:
                    if "TIT2" in tags:
                        title = str(tags["TIT2"])
                    if "TPE1" in tags:
                        artist = str(tags["TPE1"])
                    if "TALB" in tags:
                        album = str(tags["TALB"])

                    # Extract APIC cover art
                    for tag in tags.values():
                        if isinstance(tag, APIC):
                            cover_ext = "jpg" if "jpeg" in tag.mime.lower() or "jpg" in tag.mime.lower() else "png"
                            c_name = f"cover_{uuid.uuid4().hex[:10]}.{cover_ext}"
                            c_path = covers_dir / c_name
                            covers_dir.mkdir(parents=True, exist_ok=True)
                            with open(c_path, "wb") as f:
                                f.write(tag.data)
                            cover_filename = c_name
                            break

            # 2. FLAC tags
            elif isinstance(audio, FLAC):
                if audio.get("title"):
                    title = audio["title"][0]
                if audio.get("artist"):
                    artist = audio["artist"][0]
                if audio.get("album"):
                    album = audio["album"][0]

                if audio.pictures:
                    pic = audio.pictures[0]
                    cover_ext = "jpg" if "jpeg" in pic.mime.lower() or "jpg" in pic.mime.lower() else "png"
                    c_name = f"cover_{uuid.uuid4().hex[:10]}.{cover_ext}"
                    c_path = covers_dir / c_name
                    covers_dir.mkdir(parents=True, exist_ok=True)
                    with open(c_path, "wb") as f:
                        f.write(pic.data)
                    cover_filename = c_name

            # 3. MP4 / M4A / AAC
            elif isinstance(audio, MP4):
                if audio.tags:
                    if "\xa9nam" in audio.tags:
                        title = audio.tags["\xa9nam"][0]
                    if "\xa9ART" in audio.tags:
                        artist = audio.tags["\xa9ART"][0]
                    if "\xa9alb" in audio.tags:
                        album = audio.tags["\xa9alb"][0]
                    if "covr" in audio.tags and audio.tags["covr"]:
                        cov_data = audio.tags["covr"][0]
                        c_name = f"cover_{uuid.uuid4().hex[:10]}.jpg"
                        c_path = covers_dir / c_name
                        covers_dir.mkdir(parents=True, exist_ok=True)
                        with open(c_path, "wb") as f:
                            f.write(cov_data)
                        cover_filename = c_name

            # Generic fallback for dict-like tags (e.g. OGG)
            elif hasattr(audio, "tags") and audio.tags:
                tags = audio.tags
                if "title" in tags:
                    val = tags["title"]
                    title = val[0] if isinstance(val, list) else str(val)
                if "artist" in tags:
                    val = tags["artist"]
                    artist = val[0] if isinstance(val, list) else str(val)
                if "album" in tags:
                    val = tags["album"]
                    album = val[0] if isinstance(val, list) else str(val)

    except Exception as e:
        print(f"Error parsing metadata for {file_path}: {e}")

    return title, artist, album, duration, cover_filename
