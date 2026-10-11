import os
import re
import socket
import uuid
import mimetypes
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from server.db import (
    init_db, add_song, get_all_songs, get_song, delete_song, get_tasks,
    create_playlist, get_playlists, get_playlist, get_playlist_songs,
    add_song_to_playlist, remove_song_from_playlist, delete_playlist
)
from server.audio_utils import extract_metadata
from server.downloader import run_spotdl_download

# Base directories
BASE_MUSIC_DIR = Path(os.getenv("MUSIC_DATA_DIR", "music_library"))
SONGS_DIR = BASE_MUSIC_DIR / "songs"
COVERS_DIR = BASE_MUSIC_DIR / "covers"
STATIC_DIR = Path(__file__).parent / "static"

SONGS_DIR.mkdir(parents=True, exist_ok=True)
COVERS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Music Stream & Admin Hub", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Database on startup
@app.on_event("startup")
def on_startup():
    init_db()

# Request schemas
class DownloadRequest(BaseModel):
    query: str

# Helper for byte range streaming (vital for mobile scrub/seek)
def send_bytes_range_requests(
    file_path: Path, range_header: Optional[str]
) -> Response:
    file_size = file_path.stat().st_size
    content_type, _ = mimetypes.guess_type(str(file_path))
    if not content_type:
        content_type = "audio/mpeg"

    if not range_header:
        def iterfile():
            with open(file_path, mode="rb") as f:
                yield from f
        return StreamingResponse(
            iterfile(),
            media_type=content_type,
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
            },
        )

    # Parse range header e.g. "bytes=0-1024"
    range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
    if not range_match:
        raise HTTPException(status_code=416, detail="Invalid Range Header")

    start = int(range_match.group(1))
    end_str = range_match.group(2)
    end = int(end_str) if end_str else file_size - 1

    if start >= file_size or end >= file_size or start > end:
        return Response(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_size = (end - start) + 1

    def iterfile_chunk():
        with open(file_path, mode="rb") as f:
            f.seek(start)
            bytes_left = chunk_size
            while bytes_left > 0:
                read_amount = min(bytes_left, 64 * 1024)
                data = f.read(read_amount)
                if not data:
                    break
                bytes_left -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
        "Content-Type": content_type,
    }
    return StreamingResponse(iterfile_chunk(), status_code=status.HTTP_206_PARTIAL_CONTENT, headers=headers)

# Static file serving and Web Pages
@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    user_agent = request.headers.get("user-agent", "").lower()
    is_mobile = any(keyword in user_agent for keyword in ["android", "iphone", "ipad", "mobile"])
    page_to_serve = "mobile.html" if is_mobile else "desktop.html"
    file_path = STATIC_DIR / page_to_serve
    if file_path.exists():
        return HTMLResponse(content=file_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Music Server Running</h1>")

@app.get("/desktop", response_class=HTMLResponse)
async def serve_desktop():
    file_path = STATIC_DIR / "desktop.html"
    return HTMLResponse(content=file_path.read_text(encoding="utf-8"))

@app.get("/mobile", response_class=HTMLResponse)
async def serve_mobile():
    file_path = STATIC_DIR / "mobile.html"
    return HTMLResponse(content=file_path.read_text(encoding="utf-8"))

@app.get("/admin", response_class=HTMLResponse)
async def serve_admin():
    file_path = STATIC_DIR / "admin.html"
    return HTMLResponse(content=file_path.read_text(encoding="utf-8"))

@app.get("/favicon.ico", include_in_schema=False)
async def serve_favicon():
    logo_path = STATIC_DIR / "logo.png"
    if logo_path.exists():
        return FileResponse(logo_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Favicon not found")

@app.get("/style.css", include_in_schema=False)
async def serve_root_style():
    style_path = STATIC_DIR / "style.css"
    if style_path.exists():
        return FileResponse(style_path, media_type="text/css")
    raise HTTPException(status_code=404, detail="Style not found")

@app.get("/logo.png", include_in_schema=False)
async def serve_root_logo():
    logo_path = STATIC_DIR / "logo.png"
    if logo_path.exists():
        return FileResponse(logo_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Logo not found")

# API endpoints
@app.get("/api/info")
async def get_node_info():
    """Returns load-balancer node info for balancing verification"""
    return {
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "worker": os.getenv("WORKER_NAME", "worker-1")
    }

@app.get("/api/songs")
async def list_songs(q: Optional[str] = None):
    return get_all_songs(q)

@app.get("/api/songs/{song_id}")
async def song_detail(song_id: int):
    song = get_song(song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    return song

@app.get("/api/stream/{song_id}")
async def stream_song(song_id: int, request: Request):
    song = get_song(song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    # If hosted on Telegram Cloud, redirect to Telegram stream URL
    if song.get("telegram_file_id"):
        from server.telegram_storage import get_telegram_file_stream_url
        from fastapi.responses import RedirectResponse
        tg_url = get_telegram_file_stream_url(song["telegram_file_id"])
        if tg_url:
            return RedirectResponse(url=tg_url, status_code=307)

    file_path = SONGS_DIR / song["filename"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file missing on disk")
    return send_bytes_range_requests(file_path, request.headers.get("Range"))

@app.get("/api/cover/{song_id}")
async def get_cover(song_id: int):
    song = get_song(song_id)
    if song and song.get("cover_filename"):
        cover_path = COVERS_DIR / song["cover_filename"]
        if cover_path.exists():
            return FileResponse(cover_path)
    # Return placeholder SVG if no cover
    svg_fallback = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
      <defs>
        <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#ec4899"/>
          <stop offset="100%" stop-color="#8b5cf6"/>
        </linearGradient>
      </defs>
      <rect width="100" height="100" rx="16" fill="url(#g)"/>
      <path d="M40 30 v30 a8 8 0 1 0 8 8 v-26 l22 -5 v23 a8 8 0 1 0 8 8 v-35 z" fill="white" opacity="0.9"/>
    </svg>"""
    return Response(content=svg_fallback, media_type="image/svg+xml")

# Playlist APIs
class PlaylistCreateReq(BaseModel):
    name: str
    description: Optional[str] = ""

class PlaylistAddSongReq(BaseModel):
    song_id: int

@app.get("/api/playlists")
async def list_user_playlists():
    return get_playlists()

@app.post("/api/playlists")
async def create_user_playlist(req: PlaylistCreateReq):
    if not req.name or not req.name.strip():
        raise HTTPException(status_code=400, detail="Playlist name is required")
    pid = create_playlist(req.name.strip(), req.description or "")
    return {"id": pid, "name": req.name.strip()}

@app.get("/api/playlists/{playlist_id}")
async def get_single_playlist(playlist_id: int):
    playlist = get_playlist(playlist_id)
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    songs = get_playlist_songs(playlist_id)
    return {"playlist": playlist, "songs": songs}

@app.post("/api/playlists/{playlist_id}/songs")
async def add_song_to_playlist_ep(playlist_id: int, req: PlaylistAddSongReq):
    success = add_song_to_playlist(playlist_id, req.song_id)
    return {"success": success}

@app.delete("/api/playlists/{playlist_id}/songs/{song_id}")
async def remove_song_from_playlist_ep(playlist_id: int, song_id: int):
    success = remove_song_from_playlist(playlist_id, song_id)
    return {"success": success}

@app.delete("/api/playlists/{playlist_id}")
async def delete_playlist_ep(playlist_id: int):
    success = delete_playlist(playlist_id)
    return {"success": success}

@app.post("/api/upload")
async def upload_songs(files: List[UploadFile] = File(...)):
    results = []
    for file in files:
        ext = Path(file.filename or "").suffix.lower()
        if ext not in [".mp3", ".flac", ".m4a", ".wav", ".ogg", ".opus", ".aac"]:
            continue
        
        safe_name = f"{uuid.uuid4().hex[:8]}_{Path(file.filename or 'song').name}"
        saved_path = SONGS_DIR / safe_name
        
        content = await file.read()
        with open(saved_path, "wb") as f:
            f.write(content)
            
        title, artist, album, duration, cover_fn = extract_metadata(saved_path, COVERS_DIR)
        filesize = len(content)

        # Upload to Telegram Cloud if configured (saves 0 bytes on PC!)
        from server.telegram_storage import upload_audio_to_telegram, get_telegram_config
        tg_cfg = get_telegram_config()
        tg_file_id = None
        if tg_cfg.get("bot_token") and tg_cfg.get("chat_id"):
            tg_file_id = upload_audio_to_telegram(saved_path, title, artist, int(duration))
            if tg_file_id:
                # Delete from PC disk immediately - 0 bytes used on PC!
                try:
                    saved_path.unlink()
                except Exception:
                    pass

        song_id = add_song(
            title=title or Path(file.filename or 'Unknown').stem,
            artist=artist or "Unknown Artist",
            album=album or "Unknown Album",
            duration=duration,
            filename=safe_name,
            cover_filename=cover_fn,
            filesize=filesize,
            source="telegram" if tg_file_id else "upload",
            telegram_file_id=tg_file_id
        )
        
        results.append({
            "id": song_id, 
            "title": title, 
            "artist": artist, 
            "filename": safe_name, 
            "cloud": bool(tg_file_id)
        })
        
    return {"uploaded": len(results), "songs": results}

class TelegramSettingsReq(BaseModel):
    bot_token: str
    chat_id: str

@app.get("/api/telegram/config")
async def get_tg_settings():
    from server.telegram_storage import get_telegram_config
    cfg = get_telegram_config()
    token = cfg.get("bot_token", "")
    masked_token = f"{token[:6]}...{token[-4:]}" if len(token) > 10 else ("Configured" if token else "")
    return {"configured": bool(token and cfg.get("chat_id")), "chat_id": cfg.get("chat_id", ""), "token_preview": masked_token}

@app.post("/api/telegram/config")
async def save_tg_settings(req: TelegramSettingsReq):
    from server.telegram_storage import save_telegram_config, test_telegram_connection
    test = test_telegram_connection(req.bot_token, req.chat_id)
    if not test.get("ok"):
        raise HTTPException(status_code=400, detail=test.get("error", "Telegram connection failed"))
    save_telegram_config(req.bot_token, req.chat_id)
    return {"message": test.get("message", "Telegram Cloud credentials saved successfully!"), "status": "active", "bot": test.get("bot_username")}

@app.post("/api/download")
async def trigger_download(req: DownloadRequest, background_tasks: BackgroundTasks):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    task_id = uuid.uuid4().hex[:10]
    background_tasks.add_task(run_spotdl_download, task_id, req.query.strip(), SONGS_DIR, COVERS_DIR)
    return {"task_id": task_id, "status": "queued", "query": req.query}

@app.post("/api/scan")
async def scan_library():
    from server.downloader import scan_and_index_directory
    added = scan_and_index_directory(SONGS_DIR, COVERS_DIR)
    return {"message": f"Scanned library, added {added} new song(s)", "added": added}

@app.get("/api/tasks")
async def list_download_tasks():
    return get_tasks()

@app.delete("/api/songs/{song_id}")
async def remove_song(song_id: int):
    deleted = delete_song(song_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Song not found")
    
    file_path = SONGS_DIR / deleted["filename"]
    if file_path.exists():
        try:
            file_path.unlink()
        except Exception:
            pass
            
    if deleted.get("cover_filename"):
        c_path = COVERS_DIR / deleted["cover_filename"]
        if c_path.exists():
            try:
                c_path.unlink()
            except Exception:
                pass
                
    return {"message": "Song deleted successfully", "id": song_id}

# Mount static folder
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
