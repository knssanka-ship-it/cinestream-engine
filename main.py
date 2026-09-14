import os
import uuid
import logging
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from database import init_db, get_all_movies, get_movie_by_id, save_or_update_movie, delete_movie
from telegram_service import test_bot_connection, get_file_download_url
from torrent_worker import process_movie_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("cinestream_backend")

# Initialize database
init_db()

app = FastAPI(
    title="CineStream Backend & Telegram Torrent Bridge",
    description="Backend API powering CineStream Android App, torrent downloading via Hugging Face/Fly.io, and automated Telegram channel uploads.",
    version="1.0.0"
)

# Enable CORS for mobile app requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class MoviePublishRequest(BaseModel):
    id: Optional[str] = None
    title: str
    tagline: Optional[str] = ""
    synopsis: Optional[str] = ""
    year: int = 2024
    duration: int = 120
    rating: float = 8.5
    genres: List[str] = Field(default_factory=lambda: ["Action"])
    director: Optional[str] = "Director"
    cast: List[str] = Field(default_factory=list)
    poster_url: str = ""
    backdrop_url: Optional[str] = ""
    magnet_url: Optional[str] = ""
    direct_stream_url: Optional[str] = ""
    has_sinhala_sub: bool = True
    subtitle_file_name: Optional[str] = "Sinhala_Subtitle.srt"
    subtitle_content: Optional[str] = ""
    subtitle_url: Optional[str] = ""
    quality_badge: Optional[str] = "1080p Full HD"
    is_featured: bool = False

@app.get("/")
def root():
    return {
        "service": "CineStream Cloud Backend",
        "status": "online",
        "endpoints": {
            "movies_feed": "/api/movies",
            "publish_movie": "/api/movies/publish",
            "telegram_status": "/api/telegram/status"
        }
    }

@app.get("/api/health")
def health():
    return {"status": "ok", "app": "CineStream"}

@app.get("/api/telegram/status")
def telegram_status():
    """Verify Telegram Bot connectivity with provided Token & Channels"""
    bot_info = test_bot_connection()
    return {
        "bot_connection": bot_info,
        "movies_channel_id": "-1003984700777",
        "thumbnail_channel_id": "-1003771325554"
    }

@app.get("/api/movies")
def list_movies():
    """Returns all movies from database for the Android App"""
    return get_all_movies()

@app.get("/api/movies/{movie_id}")
def get_movie(movie_id: str):
    movie = get_movie_by_id(movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")
    return movie

@app.post("/api/movies/publish")
@app.post("/api/publish_movie")
def publish_movie(req: MoviePublishRequest, background_tasks: BackgroundTasks):
    """
    Called by Android App Admin Panel:
    1. Creates/Saves Movie entry
    2. Enqueues background worker to download torrent & forward to Telegram channels
    """
    movie_dict = req.dict()
    if not movie_dict.get("id"):
        movie_dict["id"] = f"movie_{uuid.uuid4().hex[:8]}"
        
    movie_dict["status"] = "processing" if movie_dict.get("magnet_url") else "ready"
    save_or_update_movie(movie_dict)
    
    # Enqueue background pipeline task
    background_tasks.add_task(process_movie_pipeline, movie_dict)
    
    return {
        "success": True,
        "message": "Movie accepted! Dispatched to Telegram pipeline worker.",
        "movie_id": movie_dict["id"],
        "status": movie_dict["status"],
        "movie": movie_dict
    }

@app.get("/api/pipeline/status/{movie_id}")
def check_movie_pipeline_status(movie_id: str):
    movie = get_movie_by_id(movie_id)
    if not movie:
        return {"status": "not_found", "message": "Movie ID not recognized"}
    return {
        "id": movie.get("id"),
        "title": movie.get("title"),
        "status": movie.get("status", "processing"),
        "telegram_thumbnail_file_id": movie.get("telegram_thumbnail_file_id"),
        "telegram_file_id": movie.get("telegram_file_id"),
        "direct_stream_url": movie.get("direct_stream_url")
    }

@app.delete("/api/movies/{movie_id}")
def remove_movie(movie_id: str):
    delete_movie(movie_id)
    return {"success": True, "message": f"Movie {movie_id} deleted"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
