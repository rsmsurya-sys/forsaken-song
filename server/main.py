import os
import re
import socket
import uuid
import mimetypes
from pathlib import Path
import json
import time
from typing import Optional, List, Dict, Set, Any

from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Request, Response, status, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from server.db import (
    init_db, add_song, get_all_songs, get_song, delete_song, get_tasks,
    create_playlist, get_playlists, get_playlist, get_playlist_songs,
    add_song_to_playlist, remove_song_from_playlist, delete_playlist,
    record_play, get_listening_history, get_time_machine_insights, get_music_dna_stats,
    get_ai_memory_insights
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

# Guaranteed JSON responses for all API endpoints (prevents HTML/text JSON decode errors in frontend)
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "error": True, "status_code": exc.status_code}
        )
    return HTMLResponse(content=f"<h1>Error {exc.status_code}</h1><p>{exc.detail}</p>", status_code=exc.status_code)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "error": True, "status_code": 500}
        )
    return HTMLResponse(content=f"<h1>Server Error</h1><p>{str(exc)}</p>", status_code=500)

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

    # If hosted on Telegram Cloud, stream directly as same-origin with range support & CORS
    if song.get("telegram_file_id"):
        from server.telegram_storage import get_telegram_file_stream_url
        import requests
        tg_url = get_telegram_file_stream_url(song["telegram_file_id"])
        if tg_url:
            range_header = request.headers.get("Range")
            headers = {"Range": range_header} if range_header else {}
            try:
                tg_res = requests.get(tg_url, headers=headers, stream=True, timeout=20)
                resp_headers = {
                    "Accept-Ranges": "bytes",
                    "Content-Type": "audio/mpeg",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                    "Access-Control-Allow-Headers": "Range, Accept-Ranges"
                }
                if "Content-Length" in tg_res.headers:
                    resp_headers["Content-Length"] = tg_res.headers["Content-Length"]
                if "Content-Range" in tg_res.headers:
                    resp_headers["Content-Range"] = tg_res.headers["Content-Range"]

                return StreamingResponse(
                    tg_res.iter_content(chunk_size=65536),
                    status_code=tg_res.status_code,
                    headers=resp_headers,
                    media_type="audio/mpeg"
                )
            except Exception as e:
                print(f"Error streaming song {song_id} from Telegram: {e}")
                from fastapi.responses import RedirectResponse
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

# ========================================================
# FORSAKEN 2.0 AI INTELLIGENCE APIS
# ========================================================
class MoodQueryReq(BaseModel):
    query: str
    shift_mode: Optional[str] = "stay"  # "stay" or "shift"
    energy_target: Optional[str] = "balanced"

class PlayHistoryReq(BaseModel):
    song_id: int
    mood_context: Optional[str] = ""
    duration_listened: Optional[float] = 0
    skipped: Optional[bool] = False

@app.post("/api/ai/mood")
async def ai_mood_engine(req: MoodQueryReq):
    query_text = (req.query or "").lower().strip()
    shift_mode = req.shift_mode or "stay"
    
    songs = get_all_songs()
    if not songs:
        return {
            "query": req.query,
            "shift_mode": shift_mode,
            "archetype": "Silent Voyager",
            "reasoning": "No songs in library yet. Add music via Admin to activate full AI Mood synthesis.",
            "songs": []
        }

    mood_keywords = {
        "sad": ["sad", "lonely", "alone", "cry", "tears", "pain", "broken", "hurt", "miss", "lost", "night"],
        "chill": ["chill", "calm", "relax", "sleep", "soft", "peace", "rain", "study", "lofi", "breeze", "ambient"],
        "energetic": ["gym", "workout", "motivation", "energy", "hype", "fast", "run", "pump", "power", "dance", "club"],
        "happy": ["happy", "smile", "joy", "party", "celebration", "fun", "vibe", "love", "feel good"],
        "focus": ["focus", "coding", "code", "work", "read", "deep", "concentration", "study", "task"]
    }

    detected_mood = "balanced"
    for m, kws in mood_keywords.items():
        if any(kw in query_text for kw in kws):
            detected_mood = m
            break

    target_mood = detected_mood
    if shift_mode == "shift":
        if detected_mood in ["sad", "lonely"]:
            target_mood = "chill" if "soft" in query_text else "happy"
        elif detected_mood == "angry":
            target_mood = "chill"

    scored_songs = []
    for s in songs:
        text = f"{s.get('title', '')} {s.get('artist', '')} {s.get('album', '')}".lower()
        score = 0
        for word in query_text.split():
            if len(word) > 2 and word in text:
                score += 15
                
        if target_mood == "sad":
            if (s.get("duration") or 0) > 240: score += 5
            if any(w in text for w in ["slow", "sad", "feel", "tears", "rain", "heart", "lonely"]): score += 10
        elif target_mood in ["energetic", "happy"]:
            if 150 < (s.get("duration") or 0) < 230: score += 5
            if any(w in text for w in ["beat", "dance", "remix", "bass", "party", "fire", "anthem"]): score += 10
        elif target_mood in ["chill", "focus"]:
            if any(w in text for w in ["lofi", "ambient", "acoustic", "theme", "piano", "calm", "melody"]): score += 10

        scored_songs.append((score, s))

    scored_songs.sort(key=lambda x: x[0], reverse=True)
    matched_songs = [item[1] for item in scored_songs[:15]]

    reasoning = (
        f"Synthesized {len(matched_songs)} tracks for your '{req.query}' context. "
        f"{'Shifting your frequency towards uplifting vibes.' if shift_mode == 'shift' else 'Matching your emotional wave directly.'}"
    )

    return {
        "query": req.query,
        "detected_mood": detected_mood,
        "shift_mode": shift_mode,
        "archetype": f"{detected_mood.capitalize()} Soundwave",
        "reasoning": reasoning,
        "songs": matched_songs
    }

@app.get("/api/ai/dna")
async def get_ai_music_dna():
    return get_music_dna_stats()

@app.get("/api/ai/time-machine")
async def get_ai_time_machine():
    return get_time_machine_insights()

@app.get("/api/ai/memory")
async def get_ai_memory():
    return get_ai_memory_insights()

class DiscoverQueryReq(BaseModel):
    query: str
    max_results: Optional[int] = 12

class FlowSessionReq(BaseModel):
    duration_minutes: Optional[int] = 60
    intent: Optional[str] = "focus"

@app.post("/api/ai/discover")
async def ai_conversational_discovery(req: DiscoverQueryReq):
    raw_query = (req.query or "").strip().lower()
    all_songs = get_all_songs()
    if not all_songs:
        return {
            "query": req.query,
            "detected_intent": "General Search",
            "conversational_insight": "No tracks currently in library. Upload music via Admin to activate deep discovery.",
            "total_duration_minutes": 0,
            "songs": []
        }

    # Detect language preference
    lang_tags = {
        "tamil": ["tamil", "anirudh", "ar rahman", "yuvan", "harris", "ilaiyaraaja", "santhosh", "sid sriram", "vaathi", "leo", "jailer", "master"],
        "hindi": ["hindi", "arijit", "pritam", "shreya", "badshah", "neha", "atif", "bollywood"],
        "english": ["english", "taylor", "weeknd", "ed sheeran", "drake", "eminem", "pop", "rock", "hollywood"],
        "malayalam": ["malayalam", "sushin", "jassie", "vineeth", "shaan"],
        "telugu": ["telugu", "thaman", "dsp", "devi", "sid sriram"]
    }
    detected_lang = None
    for lang, kws in lang_tags.items():
        if any(kw in raw_query for kw in kws):
            detected_lang = lang
            break

    # Detect duration request (e.g. "30-minute", "45 min", "1 hour")
    target_duration_secs = None
    dur_match = re.search(r'(\d+)\s*(?:-| )*(?:min|minute)', raw_query)
    if dur_match:
        target_duration_secs = int(dur_match.group(1)) * 60
    elif "1 hour" in raw_query or "one hour" in raw_query:
        target_duration_secs = 3600

    # Detect acoustic keywords
    is_vocal_heavy = any(k in raw_query for k in ["vocal", "vocals", "singing", "voice", "powerful vocal"])
    no_heavy_bass = any(k in raw_query for k in ["without heavy bass", "no bass", "light bass", "soft bass", "clean"])
    is_energetic = any(k in raw_query for k in ["energetic", "high energy", "fast", "hype", "pump", "gym", "workout"])
    is_underrated = any(k in raw_query for k in ["underrated", "hidden", "unexplored", "rare", "forgotten", "fresh"])
    is_chill = any(k in raw_query for k in ["walk", "chill", "evening", "relax", "rain", "calm", "soft", "peace"])

    # Score each track
    scored = []
    for s in all_songs:
        text = f"{s.get('title', '')} {s.get('artist', '')} {s.get('album', '')}".lower()
        score = 20  # Base resonance

        # Direct token match
        for word in raw_query.split():
            if len(word) > 2 and word in text:
                score += 25

        # Language resonance
        if detected_lang:
            if any(k in text for k in lang_tags[detected_lang]):
                score += 35
            elif detected_lang in ["tamil", "hindi"] and any(k in text for k in lang_tags["english"]):
                score -= 10

        # Vocal clarity vs bass preference
        if is_vocal_heavy and any(k in text for k in ["acoustic", "melody", "unplugged", "voice", "soul", "reprise"]):
            score += 20
        if no_heavy_bass and any(k in text for k in ["remix", "bass", "trap", "edm", "drop"]):
            score -= 30
        if is_energetic and any(k in text for k in ["remix", "beat", "club", "fast", "anthem", "dance"]):
            score += 25
        if is_chill and any(k in text for k in ["lofi", "ambient", "acoustic", "rain", "soft", "breeze"]):
            score += 25
        if is_underrated:
            score += 15

        scored.append((score, s))

    scored.sort(key=lambda x: x[0], reverse=True)

    # If duration requested, greedily accumulate songs up to target duration
    selected_songs = []
    accumulated_secs = 0
    if target_duration_secs:
        for _, s in scored:
            dur = s.get("duration") or 210
            if accumulated_secs + dur <= target_duration_secs + 90:
                selected_songs.append(s)
                accumulated_secs += dur
            if accumulated_secs >= target_duration_secs - 60:
                break
        if not selected_songs and scored:
            selected_songs = [s for _, s in scored[:min(req.max_results or 10, len(scored))]]
            accumulated_secs = sum(s.get("duration") or 210 for s in selected_songs)
    else:
        selected_songs = [s for _, s in scored[:min(req.max_results or 10, len(scored))]]
        accumulated_secs = sum(s.get("duration") or 210 for s in selected_songs)

    total_mins = round(accumulated_secs / 60, 1)

    # Conversational narrative
    insights = []
    if detected_lang:
        insights.append(f"{detected_lang.capitalize()} catalog priority")
    if is_vocal_heavy:
        insights.append("emphasizing vocal resonance and mid-frequency clarity")
    if no_heavy_bass:
        insights.append("attenuating low-end rumble for a cleaner soundstage")
    if target_duration_secs:
        insights.append(f"budgeted for a ~{target_duration_secs // 60}-minute timeframe ({total_mins}m total)")
    if is_underrated:
        insights.append("highlighting hidden gems and off-the-beaten-track tracks")

    insight_str = "Selected tracks " + ", ".join(insights) + "." if insights else "Synthesized tracks matching your situational description."

    return {
        "query": req.query,
        "conversational_insight": insight_str,
        "detected_language": detected_lang or "Universal",
        "total_duration_minutes": total_mins,
        "total_tracks": len(selected_songs),
        "songs": selected_songs
    }

@app.post("/api/ai/flow")
async def ai_forsaken_flow(req: FlowSessionReq):
    duration_mins = max(15, min(req.duration_minutes or 60, 180))
    intent = (req.intent or "focus").lower()
    all_songs = get_all_songs()

    s1_mins = max(3, round(duration_mins * 0.15))
    s2_mins = max(5, round(duration_mins * 0.55))
    s3_mins = max(3, round(duration_mins * 0.20))
    s4_mins = max(2, duration_mins - (s1_mins + s2_mins + s3_mins))

    stages = [
        {
            "id": "stage_entry",
            "stage_number": 1,
            "title": "Cognitive Settle-In",
            "target_state": "Gentle acoustic ramp & steady cadence",
            "duration_minutes": s1_mins,
            "recommended_eq": "Warm Focus (-1dB Bass, +1dB Mid)",
            "tracks": []
        },
        {
            "id": "stage_flow",
            "stage_number": 2,
            "title": "Deep Atmospheric Immersion",
            "target_state": "Consistent rhythmic pulse & high concentration lock",
            "duration_minutes": s2_mins,
            "recommended_eq": "Sonic Clarity (+2dB 1kHz, +1dB 4kHz)",
            "tracks": []
        },
        {
            "id": "stage_stabilization",
            "stage_number": 3,
            "title": "Cognitive Stabilization",
            "target_state": "Reduced stimulation & harmonic soothing",
            "duration_minutes": s3_mins,
            "recommended_eq": "Smooth Landing (-2dB Treble, +2dB Warm Low)",
            "tracks": []
        },
        {
            "id": "stage_outro",
            "stage_number": 4,
            "title": "Mindful Outro & Return",
            "target_state": "Ambient resolution & tranquil fadeout",
            "duration_minutes": s4_mins,
            "recommended_eq": "Ambient Space (+3dB Reverb/Air 16kHz)",
            "tracks": []
        }
    ]

    if all_songs:
        chunk_size = max(1, len(all_songs) // 4)
        stages[0]["tracks"] = all_songs[:chunk_size]
        stages[1]["tracks"] = all_songs[chunk_size:chunk_size*2] if len(all_songs) > chunk_size else all_songs[:chunk_size]
        stages[2]["tracks"] = all_songs[chunk_size*2:chunk_size*3] if len(all_songs) > chunk_size*2 else all_songs[:chunk_size]
        stages[3]["tracks"] = all_songs[chunk_size*3:] if len(all_songs) > chunk_size*3 else all_songs[:chunk_size]

    return {
        "intent": intent,
        "total_duration_minutes": duration_mins,
        "stages": stages,
        "flow_summary": f"{duration_mins}-Minute Adaptive Flow tailored for {intent.capitalize()}. Frequencies and pacing dynamically modulate as your session progresses."
    }


@app.get("/api/ai/bridge/{song_id}")
async def get_cross_language_bridge(song_id: int):
    target = get_song(song_id)
    if not target:
        raise HTTPException(status_code=404, detail="Song not found")

    songs = get_all_songs()
    other_songs = [s for s in songs if s["id"] != song_id]
    
    t_text = f"{target.get('title', '')} {target.get('artist', '')}".lower()
    is_tamil = any(k in t_text for k in ['tamil', 'anirudh', 'ar rahman', 'yuvan', 'harris', 'ilaiyaraaja', 'santhosh', 'sid sriram', 'vaathi', 'leo', 'jailer', 'master'])
    is_hindi = any(k in t_text for k in ['hindi', 'arijit', 'pritam', 'shreya', 'badshah', 'neha', 'atif'])
    target_lang = "Tamil" if is_tamil else ("Hindi" if is_hindi else "English/Global")

    bridge_matches = []
    for s in other_songs:
        s_text = f"{s.get('title', '')} {s.get('artist', '')}".lower()
        s_tamil = any(k in s_text for k in ['tamil', 'anirudh', 'ar rahman', 'yuvan', 'harris', 'ilaiyaraaja', 'santhosh', 'sid sriram'])
        s_hindi = any(k in s_text for k in ['hindi', 'arijit', 'pritam', 'shreya', 'badshah'])
        s_lang = "Tamil" if s_tamil else ("Hindi" if s_hindi else "English/Global")

        cross_lang = s_lang != target_lang
        duration_diff = abs((s.get("duration") or 0) - (target.get("duration") or 0))
        similarity_score = (30 if cross_lang else 10) + max(0, 20 - int(duration_diff / 10))

        bridge_matches.append({
            "song": s,
            "detected_language": s_lang,
            "bridge_score": similarity_score,
            "acoustic_resonance": "Similar vocal cadence and driving tempo across language barriers"
        })

    bridge_matches.sort(key=lambda x: x["bridge_score"], reverse=True)
    return {
        "origin_song": target,
        "origin_language": target_lang,
        "bridges": bridge_matches[:8]
    }

@app.post("/api/history/play")
async def record_playback_event(req: PlayHistoryReq):
    hid = record_play(req.song_id, req.mood_context or "", req.duration_listened or 0, req.skipped or False)
    return {"status": "recorded", "history_id": hid}

@app.get("/api/rooms")
async def get_listening_rooms():
    all_tracks = get_all_songs()
    return [
        {
            "id": "focus_pod",
            "name": "Deep Focus Sanctum",
            "description": "Binaural & ambient concentration stream with synced 25/5 Pomodoro timer.",
            "icon": "🧠",
            "theme": "indigo",
            "active_listeners": 14,
            "pomodoro_minutes": 25,
            "tracks": all_tracks[:8]
        },
        {
            "id": "emotion_sanctuary",
            "name": "Atmospheric Sanctuary",
            "description": "Midnight emotional resonance room for contemplative listening sessions.",
            "icon": "🌙",
            "theme": "cyan",
            "active_listeners": 28,
            "tracks": all_tracks[8:16] if len(all_tracks) > 8 else all_tracks[:8]
        },
        {
            "id": "sonic_battle",
            "name": "Sonic Battle Arena",
            "description": "Two musical forces collide — Vote live for the supreme track of the hour.",
            "icon": "⚡",
            "theme": "emerald",
            "active_listeners": 42,
            "tracks": all_tracks[:6]
        }
    ]

# ========================================================
# REAL-TIME SHARED LISTENING ROOMS (PARTY MODE / WEBSOCKET)
# ========================================================
class RoomConnectionManager:
    def __init__(self):
        self.rooms: Dict[str, Dict[str, Any]] = {}

    def get_or_create_room(self, room_code: str, name: str = "", host_name: str = "Host") -> Dict[str, Any]:
        room_code = room_code.strip().upper()
        if room_code not in self.rooms:
            self.rooms[room_code] = {
                "room_code": room_code,
                "name": name or f"Party Pod {room_code}",
                "host_name": host_name or "Host",
                "current_song": None,
                "is_playing": False,
                "playback_time": 0.0,
                "last_updated": time.time(),
                "connections": set()
            }
        return self.rooms[room_code]

    async def connect(self, room_code: str, websocket: WebSocket) -> Dict[str, Any]:
        await websocket.accept()
        room = self.get_or_create_room(room_code)
        room["connections"].add(websocket)
        return room

    def disconnect(self, room_code: str, websocket: WebSocket):
        room_code = room_code.strip().upper()
        if room_code in self.rooms:
            self.rooms[room_code]["connections"].discard(websocket)

    async def broadcast(self, room_code: str, message: dict, exclude: Optional[WebSocket] = None):
        room_code = room_code.strip().upper()
        if room_code in self.rooms:
            dead_connections = []
            for conn in list(self.rooms[room_code]["connections"]):
                if conn is not exclude:
                    try:
                        await conn.send_json(message)
                    except Exception:
                        dead_connections.append(conn)
            for dead in dead_connections:
                self.rooms[room_code]["connections"].discard(dead)

room_manager = RoomConnectionManager()

class CreateRoomReq(BaseModel):
    name: Optional[str] = "Live Sync Pod"
    custom_code: Optional[str] = None
    host_name: Optional[str] = "Host"

class RoomSyncReq(BaseModel):
    song: Optional[dict] = None
    is_playing: bool = False
    playback_time: float = 0.0
    is_host: bool = True

@app.post("/api/rooms/create")
async def create_live_room(req: CreateRoomReq):
    code = (req.custom_code or f"FK-{uuid.uuid4().hex[:4].upper()}").strip().upper()
    code = re.sub(r'[^A-Z0-9\-]', '', code)
    if not code:
        code = f"FK-{uuid.uuid4().hex[:4].upper()}"

    room = room_manager.get_or_create_room(code, req.name or f"Party Pod {code}", req.host_name or "Host")
    return {
        "room_code": code,
        "name": room["name"],
        "host_name": room["host_name"],
        "listeners_count": len(room["connections"])
    }

@app.get("/api/rooms/info/{room_code}")
async def get_live_room_info(room_code: str):
    code = room_code.strip().upper()
    if code not in room_manager.rooms:
        raise HTTPException(status_code=404, detail="Room not found. Please verify Room ID.")
    room = room_manager.rooms[code]
    return {
        "room_code": code,
        "name": room["name"],
        "host_name": room["host_name"],
        "current_song": room["current_song"],
        "is_playing": room["is_playing"],
        "playback_time": room["playback_time"],
        "listeners_count": len(room["connections"])
    }

@app.post("/api/rooms/sync/{room_code}")
async def sync_live_room_state(room_code: str, req: RoomSyncReq):
    code = room_code.strip().upper()
    room = room_manager.get_or_create_room(code)
    if req.is_host:
        if req.song is not None:
            room["current_song"] = req.song
        room["is_playing"] = req.is_playing
        room["playback_time"] = req.playback_time
        room["last_updated"] = time.time()
        await room_manager.broadcast(code, {
            "type": "SYNC_PLAYBACK",
            "song": room["current_song"],
            "is_playing": room["is_playing"],
            "time": room["playback_time"]
        })
    return {
        "status": "synced",
        "listeners_count": len(room["connections"]),
        "current_song": room["current_song"],
        "is_playing": room["is_playing"],
        "playback_time": room["playback_time"]
    }

@app.websocket("/ws/room/{room_code}")
async def websocket_room_endpoint(websocket: WebSocket, room_code: str):
    code = room_code.strip().upper()
    room = await room_manager.connect(code, websocket)

    # Send initial room state to newly joined friend
    await websocket.send_json({
        "type": "ROOM_STATE",
        "room_code": code,
        "name": room["name"],
        "host_name": room["host_name"],
        "current_song": room["current_song"],
        "is_playing": room["is_playing"],
        "time": room["playback_time"],
        "listeners_count": len(room["connections"])
    })

    # Broadcast updated listener count to all peers
    await room_manager.broadcast(code, {
        "type": "LISTENER_COUNT",
        "count": len(room["connections"])
    })

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except Exception:
                continue

            msg_type = msg.get("type")
            if msg_type == "SYNC_PLAYBACK":
                if "song" in msg and msg["song"]:
                    room["current_song"] = msg["song"]
                if "is_playing" in msg:
                    room["is_playing"] = bool(msg["is_playing"])
                if "time" in msg:
                    room["playback_time"] = float(msg["time"])
                room["last_updated"] = time.time()

                # Broadcast to all peers except sender
                await room_manager.broadcast(code, {
                    "type": "SYNC_PLAYBACK",
                    "song": room["current_song"],
                    "is_playing": room["is_playing"],
                    "time": room["playback_time"]
                }, exclude=websocket)

            elif msg_type == "REACTION":
                await room_manager.broadcast(code, {
                    "type": "REACTION",
                    "emoji": msg.get("emoji", "🔥"),
                    "sender": msg.get("sender", "Friend")
                })

            elif msg_type == "PING":
                await websocket.send_json({"type": "PONG", "time": time.time()})

    except WebSocketDisconnect:
        room_manager.disconnect(code, websocket)
        await room_manager.broadcast(code, {
            "type": "LISTENER_COUNT",
            "count": len(room["connections"])
        })


# Mount static folder
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

def main():
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("server.main:app", host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
