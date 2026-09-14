import os
import subprocess
import glob
import logging
import shutil
import time
import sys
import requests
from typing import Optional, Dict, Any
from telegram_service import (
    upload_thumbnail_to_channel,
    upload_video_to_movies_channel,
    upload_subtitle_to_channel
)
from database import save_or_update_movie

logger = logging.getLogger("cinestream_torrent")

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/tmp/cinestream_downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# YTS & Global Live Trackers
EXTRA_TRACKERS = (
    "&tr=udp://tracker.opentrackr.org:1337/announce"
    "&tr=udp://open.tracker.cl:1337/announce"
    "&tr=udp://open.demonii.com:1337/announce"
    "&tr=udp://tracker.openbittorrent.com:80"
    "&tr=udp://tracker.coppersurfer.tk:6969"
    "&tr=udp://glotorrents.pw:6969/announce"
    "&tr=udp://p4p.arenabg.com:1337"
    "&tr=udp://tracker.leechers-paradise.org:6969"
)

def download_media_source(source_url: str, output_dir: str, timeout_seconds: int = 1800) -> Optional[str]:
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. YouTube Video Support (yt-dlp)
    if "youtube.com" in source_url or "youtu.be" in source_url:
        print(f"🎬 [YOUTUBE DOWNLOAD] Fetching YouTube Video via yt-dlp...", flush=True)
        out_tmpl = os.path.join(output_dir, "movie.%(ext)s")
        cmd = ["yt-dlp", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best", "-o", out_tmpl, source_url]
        try:
            subprocess.run(cmd, timeout=timeout_seconds, check=True)
        except Exception as e:
            print(f"⚠️ yt-dlp error: {e}", flush=True)

    # 2. Direct HTTP/HTTPS Video Link
    elif (source_url.startswith("http://") or source_url.startswith("https://")) and not source_url.startswith("magnet:"):
        print(f"🚀 [DIRECT DOWNLOAD] Fetching direct video file...", flush=True)
        out_file = os.path.join(output_dir, "movie.mp4")
        try:
            with requests.get(source_url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(out_file, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=2*1024*1024):
                        if chunk:
                            f.write(chunk)
        except Exception as e:
            print(f"⚠️ Direct download error: {e}", flush=True)

    # 3. Magnet Torrent Download
    elif source_url.startswith("magnet:?"):
        print(f"🧲 [TORRENT DOWNLOAD] Initiating Torrent Download: {source_url[:70]}...", flush=True)
        full_magnet = source_url + EXTRA_TRACKERS if not "&tr=" in source_url else source_url
        cmd = [
            "aria2c",
            "--enable-dht=true",
            "--bt-enable-lpd=true",
            "--enable-peer-exchange=true",
            "--bt-max-peers=120",
            "--file-allocation=none",
            "--seed-time=0",
            "--summary-interval=3",
            "--dir", output_dir,
            full_magnet
        ]
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            start_time = time.time()
            for line in iter(process.stdout.readline, ""):
                clean_line = line.strip()
                if clean_line:
                    if "%" in clean_line or "DL:" in clean_line:
                        print(f"⚡ [Torrent Live] {clean_line}", flush=True)
                    elif "FILE:" in clean_line or "Complete" in clean_line:
                        print(f"📦 {clean_line}", flush=True)
                    sys.stdout.flush()

                if time.time() - start_time > timeout_seconds:
                    process.kill()
                    print("❌ Torrent download timed out.", flush=True)
                    break
            process.stdout.close()
            process.wait()
        except Exception as e:
            print(f"⚠️ Torrent engine error: {e}", flush=True)

    # Find largest video file
    video_extensions = ("*.mp4", "*.mkv", "*.avi", "*.mov", "*.webm")
    media_files = []
    for ext in video_extensions:
        media_files.extend(glob.glob(os.path.join(output_dir, "**", ext), recursive=True))

    if not media_files:
        print("❌ No video files found in output folder.", flush=True)
        return None

    largest_file = max(media_files, key=os.path.getsize)
    size_mb = os.path.getsize(largest_file) / (1024 * 1024)
    print(f"🎯 Download Complete! File: {os.path.basename(largest_file)} ({size_mb:.2f} MB)", flush=True)
    return largest_file

def process_movie_pipeline(movie_data: Dict[str, Any]):
    movie_id = movie_data["id"]
    title = movie_data.get("title", "Untitled Movie")
    magnet_url = movie_data.get("magnet_url", "")
    poster_url = movie_data.get("poster_url", "")
    has_sinhala_sub = movie_data.get("has_sinhala_sub", True)
    subtitle_name = movie_data.get("subtitle_file_name", "Sinhala.srt")
    sub_content = movie_data.get("subtitle_content", "")
    synopsis = movie_data.get("synopsis", "")

    task_dir = os.path.join(DOWNLOAD_DIR, movie_id)
    os.makedirs(task_dir, exist_ok=True)

    try:
        print(f"\n==================================================", flush=True)
        print(f"🎬 [PIPELINE START] Processing Movie: '{title}'", flush=True)
        print(f"==================================================", flush=True)

        # 1. Upload Poster Thumbnail to Channel
        if poster_url:
            thumb_caption = (
                f"🎬 <b>{title}</b> ({movie_data.get('year', 2024)})\n\n"
                f"⭐ Rating: {movie_data.get('rating', 8.0)}/10\n"
                f"🇱🇰 Sinhala Subtitles: {'✅ Yes (සිංහල උපසිරැසි සහිතයි)' if has_sinhala_sub else '❌ No'}\n\n"
                f"📖 <i>{synopsis[:250]}</i>"
            )
            print(f"🖼️ Uploading Thumbnail for '{title}'...", flush=True)
            thumb_msg_id = upload_thumbnail_to_channel(poster_url, thumb_caption)
            if thumb_msg_id:
                movie_data["telegram_thumbnail_file_id"] = thumb_msg_id
                save_or_update_movie(movie_data)
                print(f"✅ Thumbnail Uploaded Successfully!", flush=True)

        # 2. Upload Subtitle (.srt)
        if sub_content and has_sinhala_sub:
            try:
                srt_path = os.path.join(task_dir, subtitle_name or f"{title}_Sinhala.srt")
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(sub_content)
                sub_caption = f"🇱🇰 <b>{title}</b> - Official Sinhala Subtitle (.srt)"
                upload_subtitle_to_channel(srt_path, sub_caption)
            except Exception as se:
                print(f"⚠️ Subtitle notice: {se}", flush=True)

        # 3. Download Movie Video (Torrent / YouTube / Direct)
        video_file_path = None
        if magnet_url:
            video_file_path = download_media_source(magnet_url, task_dir)

        # 4. Upload Movie to Telegram Movies Channel (-1003984700777)
        if video_file_path and os.path.exists(video_file_path):
            file_size_mb = os.path.getsize(video_file_path) / (1024 * 1024)
            print(f"🚀 Uploading {file_size_mb:.2f} MB Movie to Telegram Channel (-1003984700777)...", flush=True)

            v_caption = (
                f"🎥 <b>{title} ({movie_data.get('year', 2024)})</b> Full Movie\n\n"
                f"⏱️ Duration: {movie_data.get('duration', 120)} mins | ⭐ Rating: {movie_data.get('rating', 8.0)}/10\n"
                f"🇱🇰 Sinhala Subtitles: {'✅ Available' if has_sinhala_sub else '❌ None'}\n\n"
                f"⚡ CineStream Automated Cloud Engine"
            )

            upload_res = upload_video_to_movies_channel(video_file_path, v_caption)
            if upload_res:
                movie_data["telegram_file_id"] = upload_res.get("file_id")
                movie_data["telegram_message_id"] = upload_res.get("message_id")
                movie_data["status"] = "ready"
                save_or_update_movie(movie_data)
                print(f"🎉 Movie Successfully Uploaded to Telegram!", flush=True)
            else:
                movie_data["status"] = "failed"
                save_or_update_movie(movie_data)

            shutil.rmtree(task_dir, ignore_errors=True)
        else:
            print(f"⚠️ Video file could not be downloaded.", flush=True)
            movie_data["status"] = "ready"
            save_or_update_movie(movie_data)

    except Exception as e:
        print(f"💥 [CRITICAL ERROR] {e}", flush=True)
        movie_data["status"] = "failed"
        save_or_update_movie(movie_data)
