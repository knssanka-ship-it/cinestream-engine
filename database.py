import sqlite3
import json
import os
from typing import List, Optional, Dict, Any

DB_FILE = os.environ.get("DATABASE_PATH", "cinestream.db")

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS movies (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        tagline TEXT,
        synopsis TEXT,
        year INTEGER,
        duration INTEGER,
        rating REAL,
        genres TEXT,
        director TEXT,
        cast TEXT,
        poster_url TEXT,
        backdrop_url TEXT,
        magnet_url TEXT,
        direct_stream_url TEXT,
        telegram_file_id TEXT,
        telegram_thumbnail_file_id TEXT,
        telegram_message_id INTEGER,
        has_sinhala_sub INTEGER DEFAULT 1,
        subtitle_file_name TEXT,
        subtitle_url TEXT,
        quality_badge TEXT DEFAULT '1080p Full HD',
        is_featured INTEGER DEFAULT 0,
        status TEXT DEFAULT 'ready',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()

def get_all_movies() -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM movies ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    
    movies = []
    for r in rows:
        d = dict(r)
        d["genres"] = json.loads(d["genres"]) if d.get("genres") else ["Movie"]
        d["cast"] = json.loads(d["cast"]) if d.get("cast") else []
        d["has_sinhala_sub"] = bool(d.get("has_sinhala_sub", 1))
        d["is_featured"] = bool(d.get("is_featured", 0))
        movies.append(d)
    return movies

def get_movie_by_id(movie_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM movies WHERE id = ?", (movie_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["genres"] = json.loads(d["genres"]) if d.get("genres") else []
    d["cast"] = json.loads(d["cast"]) if d.get("cast") else []
    d["has_sinhala_sub"] = bool(d.get("has_sinhala_sub", 1))
    d["is_featured"] = bool(d.get("is_featured", 0))
    return d

def save_or_update_movie(movie: Dict[str, Any]):
    conn = get_db()
    cursor = conn.cursor()
    
    genres_json = json.dumps(movie.get("genres", ["Movie"]))
    cast_json = json.dumps(movie.get("cast", []))
    
    cursor.execute("""
    INSERT INTO movies (
        id, title, tagline, synopsis, year, duration, rating,
        genres, director, cast, poster_url, backdrop_url,
        magnet_url, direct_stream_url, telegram_file_id,
        telegram_thumbnail_file_id, telegram_message_id,
        has_sinhala_sub, subtitle_file_name, subtitle_url,
        quality_badge, is_featured, status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        title=excluded.title,
        synopsis=excluded.synopsis,
        poster_url=excluded.poster_url,
        direct_stream_url=excluded.direct_stream_url,
        telegram_file_id=excluded.telegram_file_id,
        telegram_thumbnail_file_id=excluded.telegram_thumbnail_file_id,
        has_sinhala_sub=excluded.has_sinhala_sub,
        subtitle_file_name=excluded.subtitle_file_name,
        status=excluded.status
    """, (
        movie.get("id"),
        movie.get("title"),
        movie.get("tagline", ""),
        movie.get("synopsis", ""),
        int(movie.get("year", 2024)),
        int(movie.get("duration", 120)),
        float(movie.get("rating", 8.0)),
        genres_json,
        movie.get("director", "Director"),
        cast_json,
        movie.get("poster_url", ""),
        movie.get("backdrop_url", ""),
        movie.get("magnet_url", ""),
        movie.get("direct_stream_url", ""),
        movie.get("telegram_file_id", ""),
        movie.get("telegram_thumbnail_file_id", ""),
        movie.get("telegram_message_id", 0),
        1 if movie.get("has_sinhala_sub", True) else 0,
        movie.get("subtitle_file_name", ""),
        movie.get("subtitle_url", ""),
        movie.get("quality_badge", "1080p Full HD"),
        1 if movie.get("is_featured", False) else 0,
        movie.get("status", "ready")
    ))
    conn.commit()
    conn.close()

def get_pending_movies() -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM movies WHERE status = 'queued' ORDER BY created_at ASC")
    rows = cursor.fetchall()
    conn.close()
    movies = []
    for r in rows:
        d = dict(r)
        d["genres"] = json.loads(d["genres"]) if d.get("genres") else ["Movie"]
        d["cast"] = json.loads(d["cast"]) if d.get("cast") else []
        d["has_sinhala_sub"] = bool(d.get("has_sinhala_sub", 1))
        d["is_featured"] = bool(d.get("is_featured", 0))
        movies.append(d)
    return movies

def update_movie_status(movie_id: str, status: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE movies SET status = ? WHERE id = ?", (status, movie_id))
    conn.commit()
    conn.close()

def delete_movie(movie_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM movies WHERE id = ?", (movie_id,))
    conn.commit()
    conn.close()
