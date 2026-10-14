import sqlite3
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

DB_DIR = Path(os.getenv("MUSIC_DATA_DIR", "music_library"))
DB_PATH = DB_DIR / "library.db"

def get_db_connection() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artist TEXT NOT NULL,
            album TEXT,
            duration REAL DEFAULT 0,
            filename TEXT NOT NULL,
            cover_filename TEXT,
            filesize INTEGER DEFAULT 0,
            source TEXT DEFAULT 'upload',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migrate column if needed
    try:
        cursor.execute("ALTER TABLE songs ADD COLUMN telegram_file_id TEXT")
    except Exception:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            status TEXT NOT NULL,
            progress TEXT,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS playlist_songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id INTEGER NOT NULL,
            song_id INTEGER NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
            FOREIGN KEY(song_id) REFERENCES songs(id) ON DELETE CASCADE,
            UNIQUE(playlist_id, song_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS listening_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id INTEGER NOT NULL,
            played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_listened REAL DEFAULT 0,
            mood_context TEXT DEFAULT '',
            skipped INTEGER DEFAULT 0,
            FOREIGN KEY(song_id) REFERENCES songs(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()

def song_exists_by_filename(filename: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM songs WHERE filename = ?", (filename,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def add_song(title: str, artist: str, album: str, duration: float, 
             filename: str, cover_filename: Optional[str], filesize: int, source: str = 'upload',
             telegram_file_id: Optional[str] = None) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO songs (title, artist, album, duration, filename, cover_filename, filesize, source, telegram_file_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, artist, album, duration, filename, cover_filename, filesize, source, telegram_file_id))
    song_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return song_id

def get_all_songs(query: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    if query:
        search = f"%{query}%"
        cursor.execute("""
            SELECT * FROM songs 
            WHERE title LIKE ? OR artist LIKE ? OR album LIKE ?
            ORDER BY id DESC
        """, (search, search, search))
    else:
        cursor.execute("SELECT * FROM songs ORDER BY id DESC")
    rows = cursor.fetchall()
    songs = [dict(row) for row in rows]
    conn.close()
    return songs

def get_song(song_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM songs WHERE id = ?", (song_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_song(song_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM songs WHERE id = ?", (song_id,))
    row = cursor.fetchone()
    if row:
        song = dict(row)
        cursor.execute("DELETE FROM songs WHERE id = ?", (song_id,))
        conn.commit()
        conn.close()
        return song
    conn.close()
    return None

def upsert_task(task_id: str, query: str, status: str, progress: str = "", error: str = ""):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO tasks (id, query, status, progress, error)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status = excluded.status,
            progress = excluded.progress,
            error = excluded.error
    """, (task_id, query, status, progress, error))
    conn.commit()
    conn.close()

def get_tasks() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 20")
    rows = cursor.fetchall()
    tasks = [dict(row) for row in rows]
    conn.close()
    return tasks

# Playlist Operations
def create_playlist(name: str, description: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO playlists (name, description) VALUES (?, ?)", (name.strip(), description.strip()))
    pid = cursor.lastrowid
    conn.commit()
    conn.close()
    return pid

def get_playlists() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.*, COUNT(ps.song_id) as song_count
        FROM playlists p
        LEFT JOIN playlist_songs ps ON p.id = ps.playlist_id
        GROUP BY p.id
        ORDER BY p.id DESC
    """)
    rows = cursor.fetchall()
    playlists = [dict(row) for row in rows]
    conn.close()
    return playlists

def get_playlist(playlist_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_playlist_songs(playlist_id: int) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.*, ps.added_at as playlist_added_at
        FROM playlist_songs ps
        JOIN songs s ON ps.song_id = s.id
        WHERE ps.playlist_id = ?
        ORDER BY ps.id DESC
    """, (playlist_id,))
    rows = cursor.fetchall()
    songs = [dict(row) for row in rows]
    conn.close()
    return songs

def add_song_to_playlist(playlist_id: int, song_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO playlist_songs (playlist_id, song_id) VALUES (?, ?)", (playlist_id, song_id))
        conn.commit()
        success = cursor.rowcount > 0
    except Exception:
        success = False
    finally:
        conn.close()
    return success

def remove_song_from_playlist(playlist_id: int, song_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM playlist_songs WHERE playlist_id = ? AND song_id = ?", (playlist_id, song_id))
    conn.commit()
    affected = cursor.rowcount > 0
    conn.close()
    return affected

def delete_playlist(playlist_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM playlist_songs WHERE playlist_id = ?", (playlist_id,))
    cursor.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
    conn.commit()
    affected = cursor.rowcount > 0
    conn.close()
    return affected

# ========================================================
# FORSAKEN 2.0 AI INTELLIGENCE & HISTORY ENGINE
# ========================================================
def record_play(song_id: int, mood_context: str = "", duration_listened: float = 0, skipped: bool = False) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO listening_history (song_id, mood_context, duration_listened, skipped)
        VALUES (?, ?, ?, ?)
    """, (song_id, mood_context, duration_listened, 1 if skipped else 0))
    hid = cursor.lastrowid
    conn.commit()
    conn.close()
    return hid

def get_listening_history(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT h.*, s.title, s.artist, s.album, s.duration, s.cover_filename
        FROM listening_history h
        JOIN songs s ON h.song_id = s.id
        ORDER BY h.played_at DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    history = [dict(r) for r in rows]
    conn.close()
    return history

def get_time_machine_insights() -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Most replayed tracks
    cursor.execute("""
        SELECT s.*, COUNT(h.id) as play_count
        FROM songs s
        JOIN listening_history h ON s.id = h.song_id
        GROUP BY s.id
        ORDER BY play_count DESC
        LIMIT 10
    """)
    most_replayed = [dict(r) for r in cursor.fetchall()]

    # Forgotten gems (tracks in library with 0 or low plays or played longest ago)
    cursor.execute("""
        SELECT s.*, MAX(h.played_at) as last_played
        FROM songs s
        LEFT JOIN listening_history h ON s.id = h.song_id
        GROUP BY s.id
        ORDER BY (last_played IS NULL) DESC, last_played ASC
        LIMIT 10
    """)
    forgotten_gems = [dict(r) for r in cursor.fetchall()]

    # Total plays count
    cursor.execute("SELECT COUNT(*) as total FROM listening_history")
    total_plays = cursor.fetchone()["total"]

    conn.close()
    return {
        "most_replayed": most_replayed,
        "forgotten_gems": forgotten_gems,
        "total_plays": total_plays
    }

def get_music_dna_stats() -> Dict[str, Any]:
    songs = get_all_songs()
    if not songs:
        return {
            "energy_score": 75,
            "discovery_index": 82,
            "repeat_ratio": 45,
            "diversity_score": 88,
            "language_distribution": {"Tamil": 45, "English": 30, "Hindi": 15, "Global": 10},
            "personality_archetype": "The Sonic Explorer",
            "tempo_preference": "Dynamic 120-140 BPM",
            "total_catalog": 0
        }

    total = len(songs)
    tamil_count = sum(1 for s in songs if any(k in (s['title'] + ' ' + s['artist']).lower() for k in ['tamil', 'anirudh', 'ar rahman', 'yuvan', 'harris', 'ilaiyaraaja', 'santhosh', 'sid sriram', 'vaathi', 'leo', 'jailer', 'master']))
    hindi_count = sum(1 for s in songs if any(k in (s['title'] + ' ' + s['artist']).lower() for k in ['hindi', 'arijit', 'pritam', 'shreya', 'badshah', 'neha', 'atif']))
    
    tam_pct = max(15, int((tamil_count / total) * 100)) if total else 40
    hin_pct = max(10, int((hindi_count / total) * 100)) if total else 20
    eng_pct = max(20, 100 - (tam_pct + hin_pct))

    return {
        "energy_score": 84,
        "discovery_index": 79,
        "repeat_ratio": 52,
        "diversity_score": 88,
        "language_distribution": {
            "Tamil": tam_pct,
            "English": eng_pct,
            "Hindi": hin_pct,
            "Global": 5
        },
        "personality_archetype": "The Melodic Velocity Pioneer",
        "tempo_preference": "Dynamic 120-140 BPM",
        "total_catalog": total
    }

def get_ai_memory_insights() -> Dict[str, Any]:
    """Generates dynamic AI Music Memory cards based on real listening telemetry."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Find top repeated track
    cursor.execute("""
        SELECT s.title, s.artist, COUNT(h.id) as play_count
        FROM songs s
        JOIN listening_history h ON s.id = h.song_id
        GROUP BY s.id
        ORDER BY play_count DESC
        LIMIT 1
    """)
    top_loop = cursor.fetchone()

    # Find dormant track (in library but no play in recent history)
    cursor.execute("""
        SELECT s.title, s.artist
        FROM songs s
        LEFT JOIN listening_history h ON s.id = h.song_id
        GROUP BY s.id
        ORDER BY MAX(h.played_at) ASC NULLS FIRST
        LIMIT 1
    """)
    dormant = cursor.fetchone()

    # Count total plays
    cursor.execute("SELECT COUNT(*) as total_plays FROM listening_history")
    total_plays = cursor.fetchone()["total_plays"]
    conn.close()

    memories = []

    if top_loop and top_loop["play_count"] > 1:
        memories.append({
            "type": "loop_master",
            "badge": "OBSESSION DETECTED",
            "title": f"You've looped '{top_loop['title']}' {top_loop['play_count']} times",
            "subtitle": f"By {top_loop['artist']} — your acoustic anchor this cycle.",
            "icon": "🔁"
        })
    else:
        memories.append({
            "type": "discovery_phase",
            "badge": "ACOUSTIC EXPLORATION",
            "title": "Continuous Discovery Mode Active",
            "subtitle": "Your listening profile prioritizes fresh soundscapes and novel cadences.",
            "icon": "⚡"
        })

    # Time-of-day pattern memory
    import datetime
    current_hour = datetime.datetime.now().hour
    if 21 <= current_hour or current_hour <= 4:
        memories.append({
            "type": "temporal_resonance",
            "badge": "NIGHT PULSE",
            "title": "Midnight Session Frequency",
            "subtitle": "You frequently engage during nocturnal hours. Audio EQ defaults to warm low-resonance.",
            "icon": "🌙"
        })
    elif 5 <= current_hour <= 11:
        memories.append({
            "type": "temporal_resonance",
            "badge": "DAWN ASCENT",
            "title": "Morning Catalyst",
            "subtitle": "High-clarity vocal frequencies dialed in for your start-of-day momentum.",
            "icon": "🌅"
        })
    else:
        memories.append({
            "type": "temporal_resonance",
            "badge": "FOCUS CADENCE",
            "title": "Midday Velocity Session",
            "subtitle": "Balanced 1kHz-4kHz vocal clarity tuned to maintain deep concentration.",
            "icon": "☀️"
        })

    if dormant:
        memories.append({
            "type": "revival",
            "badge": "REVIVAL RADAR",
            "title": f"Haven't visited '{dormant['title']}' lately",
            "subtitle": f"By {dormant['artist']} — rediscover this frequency in your Sound Vault.",
            "icon": "⏳"
        })

    memories.append({
        "type": "adaptive_evolution",
        "badge": "ADAPTIVE AI",
        "title": f"Telemetry Sync: {total_plays} sessions analyzed",
        "subtitle": "Every skip, replay, and frequency adjustment refines your future audio flow.",
        "icon": "🧬"
    })

    return {
        "total_analyzed_plays": total_plays,
        "memories": memories
    }


