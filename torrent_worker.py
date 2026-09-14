import os
import subprocess
import glob
import logging
import shutil
import time
import sys
from typing import Optional, Dict, Any
from telegram_service import (
    upload_thumbnail_to_channel,
    upload_video_to_movies_channel,
    upload_subtitle_to_channel,
    get_file_download_url
)
from database import save_or_update_movie, update_movie_status

logger = logging.getLogger("cinestream_torrent")

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/tmp/cinestream_downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.tracker.cl:1337/announce",
    "udp://opentracker.i2p.rocks:6969/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://explodie.org:6969/announce",
    "udp://tracker.coppersurfer.tk:6969/announce",
    "http://tracker.openbittorrent.com:80/announce",
    "udp://9.rarbg.to:2710/announce",
    "udp://tracker.cyberia.is:6969/announce"
]

def download_magnet(magnet_url: str, output_dir: str, timeout_seconds: int = 1800) -> Optional[str]:
    """
    Downloads torrent/magnet link via aria2c with live logging.
    Returns path to the largest media file (.mp4, .mkv, .webm, etc.)
    """
    os.makedirs(output_dir, exist_ok=True)
    logger.info(f"🚀 [ARIA2C START] Initiating high-speed torrent download into: {output_dir}")
    print(f"🚀 [ARIA2C START] Downloading Magnet: {magnet_url[:80]}...", flush=True)

    cmd = [
        "aria2c",
        "--enable-dht=true",
        "--enable-peer-exchange=true",
        "--bt-enable-lpd=true",
        "--bt-max-peers=150",
        "--bt-tracker=" + ",".join(TRACKERS),
        "--follow-torrent=mem",
        "--file-allocation=none",
        "--max-connection-per-server=16",
        "--split=16",
        "--min-split-size=1M",
        "--seed-time=0",
        "--summary-interval=2",
        "--dir", output_dir,
        magnet_url
    ]

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        start_time = time.time()
        for line in iter(process.stdout.readline, ""):
            clean_line = line.strip()
            if clean_line:
                # Log progress directly to stdout for live Hugging Face Logs
                if "%" in clean_line or "DL:" in clean_line or "ETA" in clean_line:
                    print(f"⚡ [Torrent Live] {clean_line}", flush=True)
                else:
                    logger.info(f"[aria2c] {clean_line}")
                    sys.stdout.flush()

            if time.time() - start_time > timeout_seconds:
                process.kill()
                logger.error("❌ [aria2c] Torrent download timed out!")
                print("❌ [aria2c] Torrent download timed out!", flush=True)
                return None

        process.stdout.close()
        return_code = process.wait()
        logger.info(f"✅ [aria2c] Download finished with exit code: {return_code}")
        print(f"✅ [aria2c] Download complete! Checking downloaded files...", flush=True)

    except Exception as e:
        logger.error(f"❌ [aria2c] Execution error: {e}", exc_info=True)
        print(f"❌ [aria2c] Execution error: {e}", flush=True)

    # Locate media file
    video_extensions = ("*.mp4", "*.mkv", "*.avi", "*.mov", "*.webm")
    media_files = []
    for ext in video_extensions:
        media_files.extend(glob.glob(os.path.join(output_dir, "**", ext), recursive=True))

    if not media_files:
        logger.error("❌ No video files found in download folder.")
        print("❌ No video files found in download folder.", flush=True)
        return None

    largest_file = max(media_files, key=os.path.getsize)
    size_mb = os.path.getsize(largest_file) / (1024 * 1024)
    logger.info(f"🎯 Largest movie file: {largest_file} ({size_mb:.2f} MB)")
    print(f"🎯 Found Movie File: {os.path.basename(largest_file)} ({size_mb:.2f} MB)", flush=True)
    return largest_file

def process_movie_pipeline(movie_data: Dict[str, Any]):
    """
    Complete Background Pipeline:
    1. Uploads poster thumbnail to Telegram Thumbnail Channel (-1003771325554)
    2. Downloads torrent/magnet video to cloud container via aria2c
    3. Uploads downloaded video to Telegram Movies Channel (-1003984700777)
    4. Attaches Sinhala Subtitles
    5. Saves streaming metadata in database
    """
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

        # 1. Upload Thumbnail
        thumb_file_id = None
        if poster_url:
            thumb_caption = (
                f"🎬 <b>{title}</b> ({movie_data.get('year', 2024)})\n\n"
                f"⭐ Rating: {movie_data.get('rating', 8.0)}/10\n"
                f"🎭 Genres: {', '.join(movie_data.get('genres', []))}\n"
                f"🇱🇰 Sinhala Subtitles: {'✅ Yes (සිංහල උපසිරැසි සහිතයි)' if has_sinhala_sub else '❌ No'}\n\n"
                f"📖 <i>{synopsis[:250]}</i>"
            )
            print(f"🖼️ Uploading Thumbnail for '{title}' to Channel...", flush=True)
            thumb_file_id = upload_thumbnail_to_channel(poster_url, thumb_caption)
            if thumb_file_id:
                movie_data["telegram_thumbnail_file_id"] = thumb_file_id
                save_or_update_movie(movie_data)
                print(f"✅ Thumbnail Uploaded Successfully! File ID: {thumb_file_id}", flush=True)
            else:
                print(f"⚠️ Thumbnail Upload Warning: file_id is empty", flush=True)

        # 2. Upload Subtitle if provided
        if sub_content and has_sinhala_sub:
            try:
                srt_path = os.path.join(task_dir, subtitle_name or f"{title}_Sinhala.srt")
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(sub_content)
                sub_caption = f"🇱🇰 <b>{title}</b> - Official Sinhala Subtitle (.srt)"
                print(f"📝 Uploading Sinhala Subtitle: {subtitle_name}...", flush=True)
                sub_file_id = upload_subtitle_to_channel(srt_path, sub_caption)
                if sub_file_id:
                    movie_data["telegram_subtitle_file_id"] = sub_file_id
                    print(f"✅ Subtitle Uploaded Successfully! File ID: {sub_file_id}", flush=True)
            except Exception as se:
                print(f"⚠️ Subtitle upload notice: {se}", flush=True)

        # 3. Torrent Download
        video_file_path = None
        if magnet_url and magnet_url.startswith("magnet:?"):
            print(f"📥 Starting Torrent Download via aria2c for: {title}...", flush=True)
            video_file_path = download_magnet(magnet_url, task_dir)

        # 4. Upload Video to Movies Channel (-1003984700777)
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
                v_file_id = upload_res.get("file_id")
                movie_data["telegram_file_id"] = v_file_id
                movie_data["telegram_message_id"] = upload_res.get("message_id")
                stream_link = get_file_download_url(v_file_id)
                if stream_link:
                    movie_data["direct_stream_url"] = stream_link
                movie_data["status"] = "ready"
                save_or_update_movie(movie_data)
                print(f"🎉 Movie Successfully Uploaded to Telegram! File ID: {v_file_id}", flush=True)
            else:
                print(f"❌ Video upload to Telegram failed. Marking status.", flush=True)
                movie_data["status"] = "failed"
                save_or_update_movie(movie_data)

            # Cleanup temporary disk space
            shutil.rmtree(task_dir, ignore_errors=True)
            print(f"🧹 Cleaned up temporary files for: {title}", flush=True)
        else:
            print(f"⚠️ No downloaded video file to upload for '{title}'.", flush=True)
            movie_data["status"] = "ready"
            save_or_update_movie(movie_data)

    except Exception as e:
        print(f"💥 [CRITICAL PIPELINE ERROR] {e}", flush=True)
        logger.error(f"Pipeline error for '{title}': {e}", exc_info=True)
        movie_data["status"] = "failed"
        save_or_update_movie(movie_data)
