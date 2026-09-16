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



# Top 20 Global Trackers

GLOBAL_TRACKERS = [

    "http://tracker.opentrackr.org:1337/announce",

    "http://open.acgnxtracker.com:80/announce",

    "http://tracker.bt4g.com:2095/announce",

    "https://tracker.tamersunion.org:443/announce",

    "udp://tracker.opentrackr.org:1337/announce",

    "udp://open.tracker.cl:1337/announce",

    "udp://opentracker.i2p.rocks:6969/announce",

    "udp://tracker.openbittorrent.com:6969/announce",

    "udp://tracker.torrent.eu.org:451/announce",

    "udp://open.demonii.com:1337/announce",

    "udp://explodie.org:6969/announce",

    "udp://9.rarbg.to:2710/announce",

    "udp://p4p.arenabg.com:1337/announce"

]



def download_media_source(source_url: str, output_dir: str, timeout_seconds: int = 1800) -> Optional[str]:

    """

    Downloads Torrent with strict 512MB RAM preservation.

    Writes directly to disk scratch space without buffering into RAM.

    """

    os.makedirs(output_dir, exist_ok=True)

   

    # 1. Direct HTTP/HTTPS Video URL Support

    if source_url.startswith("http://") or source_url.startswith("https://"):

        print(f"🚀 [DIRECT DOWNLOAD] Fetching video from URL...", flush=True)

        out_file = os.path.join(output_dir, "movie.mp4")

        cmd = ["curl", "-L", "-o", out_file, source_url]

        try:

            subprocess.run(cmd, timeout=timeout_seconds, check=True)

            if os.path.exists(out_file) and os.path.getsize(out_file) > 1024 * 1024:

                return out_file

        except Exception as e:

            print(f"⚠️ Direct download notice: {e}", flush=True)



    # 2. Torrent / Magnet Download (Strict RAM limit < 32MB)

    print(f"🚀 [ARIA2C START] Downloading: {source_url[:75]}...", flush=True)

    trackers_param = "--bt-tracker=" + ",".join(GLOBAL_TRACKERS)

   

    cmd = [

        "aria2c",

        "--enable-dht=true",

        "--enable-dht6=false",

        "--dht-entry-point=dht.transmissionbt.com:6881",

        "--dht-entry-point=router.bittorrent.com:6881",

        "--peer-id-prefix=-TR3000-",

        "--user-agent=Transmission/3.00",

        "--enable-peer-exchange=true",

        "--bt-max-peers=80",

        "--bt-request-peer-speed-limit=0",

        "--file-allocation=none",

        "--disk-cache=16M",

        "--max-connection-per-server=8",

        "--split=8",

        "--seed-time=0",

        "--summary-interval=2",

        "--listen-port=6881-6999",

        "--dht-listen-port=6881-6999",

        "--follow-torrent=mem",

        "--dir", output_dir,

        trackers_param,

        source_url

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

                if "%" in clean_line or "DL:" in clean_line or "ETA" in clean_line:

                    print(f"⚡ [Torrent Live] {clean_line}", flush=True)

                elif "FILE:" in clean_line or "Download complete" in clean_line:

                    print(f"📦 {clean_line}", flush=True)

                sys.stdout.flush()



            if time.time() - start_time > timeout_seconds:

                process.kill()

                print("❌ [aria2c] Download timed out!", flush=True)

                return None



        process.stdout.close()

        process.wait()



    except Exception as e:

        print(f"❌ [aria2c] Execution error: {e}", flush=True)



    # Search for downloaded video file

    video_extensions = ("*.mp4", "*.mkv", "*.avi", "*.mov", "*.webm")

    media_files = []

    for ext in video_extensions:

        media_files.extend(glob.glob(os.path.join(output_dir, "**", ext), recursive=True))



    if not media_files:

        print("❌ No video files found in download folder.", flush=True)

        return None



    largest_file = max(media_files, key=os.path.getsize)

    size_mb = os.path.getsize(largest_file) / (1024 * 1024)

    print(f"🎯 Download Succeeded! File: {os.path.basename(largest_file)} ({size_mb:.2f} MB)", flush=True)

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



        # 1. Upload Thumbnail to -1003771325554

        thumb_file_id = None

        if poster_url:

            thumb_caption = (

                f"🎬 <b>{title}</b> ({movie_data.get('year', 2024)})\n\n"

                f"⭐ Rating: {movie_data.get('rating', 8.0)}/10\n"

                f"🇱🇰 Sinhala Subtitles: {'✅ Yes (සිංහල උපසිරැසි සහිතයි)' if has_sinhala_sub else '❌ No'}\n\n"

                f"📖 <i>{synopsis[:250]}</i>"

            )

            print(f"🖼️ Uploading Thumbnail for '{title}'...", flush=True)

            thumb_file_id = upload_thumbnail_to_channel(poster_url, thumb_caption)

            if thumb_file_id:

                movie_data["telegram_thumbnail_file_id"] = thumb_file_id

                save_or_update_movie(movie_data)

                print(f"✅ Thumbnail Uploaded Successfully! ID: {thumb_file_id}", flush=True)



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



        # 3. Download Torrent / Video Media

        video_file_path = None

        if magnet_url:

            video_file_path = download_media_source(magnet_url, task_dir)



        # 4. Stream Video directly to Telegram Channel (-1003984700777)

        if video_file_path and os.path.exists(video_file_path):

            file_size_mb = os.path.getsize(video_file_path) / (1024 * 1024)

            print(f"🚀 Streaming {file_size_mb:.2f} MB Movie to Telegram Channel (-1003984700777)...", flush=True)



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

                upload_msg_id = upload_res.get("message_id")

                movie_data["telegram_message_id"] = upload_msg_id

                if upload_msg_id:

                    movie_data["telegram_post_url"] = f"https://t.me/cinestream_lk/{upload_msg_id}"

                    if not movie_data.get("video_url") or "t.me" in movie_data.get("video_url", ""):

                        movie_data["video_url"] = f"https://t.me/cinestream_lk/{upload_msg_id}"

                stream_link = get_file_download_url(v_file_id)

                if stream_link:

                    movie_data["direct_stream_url"] = stream_link

                movie_data["status"] = "ready"

                save_or_update_movie(movie_data)

                print(f"🎉 Movie Successfully Uploaded to Telegram! File ID: {v_file_id}", flush=True)

            else:

                movie_data["status"] = "failed"

                save_or_update_movie(movie_data)



            # Free up scratch disk immediately

            shutil.rmtree(task_dir, ignore_errors=True)

            print(f"🧹 Temporary storage cleaned.", flush=True)

        else:

            print(f"⚠️ Video file could not be downloaded.", flush=True)

            movie_data["status"] = "ready"

            save_or_update_movie(movie_data)



    except Exception as e:

        print(f"💥 [CRITICAL PIPELINE ERROR] {e}", flush=True)

        movie_data["status"] = "failed"

        save_or_update_movie(movie_data)
