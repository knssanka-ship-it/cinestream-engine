import os
import requests
import json
import logging
import time
from typing import Optional, Dict, Any

logger = logging.getLogger("telegram_service")

# Bot credentials
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8784845752:AAFSX0fkHyALs79xgp8RNs9LExV9LeLyBQs")
MOVIES_CHANNEL_ID = os.environ.get("MOVIES_CHANNEL_ID", "-1003984700777")
THUMBNAIL_CHANNEL_ID = os.environ.get("THUMBNAIL_CHANNEL_ID", "-1003771325554")

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

def test_bot_connection(retries: int = 3) -> Dict[str, Any]:
    """Tests if the Telegram bot token is valid and active with auto-retries"""
    url = f"{TELEGRAM_API_BASE}/getMe"
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return data
        except Exception as e:
            logger.warning(f"Telegram getMe attempt {attempt} failed: {e}")
            time.sleep(1.5)
    return {"ok": False, "error": "Connection timed out"}

def upload_thumbnail_to_channel(image_url_or_path: str, caption: str) -> Optional[str]:
    """Uploads movie thumbnail/poster to the Thumbnail Channel (-1003771325554)"""
    url = f"{TELEGRAM_API_BASE}/sendPhoto"
    for attempt in range(1, 4):
        try:
            if image_url_or_path.startswith("http://") or image_url_or_path.startswith("https://"):
                data = {
                    "chat_id": THUMBNAIL_CHANNEL_ID,
                    "photo": image_url_or_path,
                    "caption": caption,
                    "parse_mode": "HTML"
                }
                resp = requests.post(url, data=data, timeout=45)
            else:
                with open(image_url_or_path, "rb") as f:
                    data = {
                        "chat_id": THUMBNAIL_CHANNEL_ID,
                        "caption": caption,
                        "parse_mode": "HTML"
                    }
                    resp = requests.post(url, data=data, files={"photo": f}, timeout=60)
            
            result = resp.json()
            if result.get("ok"):
                photos = result["result"].get("photo", [])
                if photos:
                    return photos[-1]["file_id"]
            else:
                print(f"⚠️ Telegram sendPhoto warning (Attempt {attempt}): {result}", flush=True)
        except Exception as e:
            print(f"⚠️ Telegram sendPhoto exception (Attempt {attempt}): {e}", flush=True)
            time.sleep(2)
    return None

def upload_video_to_movies_channel(video_path: str, caption: str, thumb_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Uploads movie video file to the Movies Channel (-1003984700777).
    Supports video & document upload modes with extended 30-minute timeouts.
    """
    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    print(f"📤 Preparing Telegram upload for file size: {file_size_mb:.2f} MB...", flush=True)

    # 1. Attempt sendVideo (supports native streaming player in Telegram)
    url = f"{TELEGRAM_API_BASE}/sendVideo"
    data = {
        "chat_id": MOVIES_CHANNEL_ID,
        "caption": caption,
        "parse_mode": "HTML",
        "supports_streaming": "true"
    }

    try:
        with open(video_path, "rb") as vf:
            files = {"video": vf}
            if thumb_path and os.path.exists(thumb_path):
                files["thumbnail"] = open(thumb_path, "rb")

            print(f"🚀 Streaming {file_size_mb:.2f} MB video bytes to Telegram API...", flush=True)
            resp = requests.post(url, data=data, files=files, timeout=1800)

        result = resp.json()
        if result.get("ok"):
            video_info = result["result"].get("video", {})
            return {
                "file_id": video_info.get("file_id"),
                "message_id": result["result"].get("message_id"),
                "channel_id": MOVIES_CHANNEL_ID,
                "duration": video_info.get("duration", 0),
                "file_size": video_info.get("file_size", 0)
            }
        else:
            print(f"⚠️ sendVideo response error: {result}. Trying sendDocument fallback...", flush=True)

            # 2. Fallback to sendDocument (handles large files without video encoding constraints)
            doc_url = f"{TELEGRAM_API_BASE}/sendDocument"
            with open(video_path, "rb") as vf:
                doc_resp = requests.post(
                    doc_url,
                    data={"chat_id": MOVIES_CHANNEL_ID, "caption": caption, "parse_mode": "HTML"},
                    files={"document": vf},
                    timeout=1800
                )
            doc_result = doc_resp.json()
            if doc_result.get("ok"):
                doc_info = doc_result["result"].get("document", {})
                return {
                    "file_id": doc_info.get("file_id"),
                    "message_id": doc_result["result"].get("message_id"),
                    "channel_id": MOVIES_CHANNEL_ID,
                    "file_size": doc_info.get("file_size", 0)
                }
            else:
                print(f"❌ sendDocument fallback error response: {doc_result}", flush=True)

    except Exception as e:
        print(f"❌ Telegram video upload exception: {e}", flush=True)
        logger.error(f"Failed to upload video: {e}")

    return None

def upload_subtitle_to_channel(srt_path: str, caption: str) -> Optional[str]:
    """Uploads Sinhala Subtitle (.srt) document to the Movies Channel"""
    try:
        url = f"{TELEGRAM_API_BASE}/sendDocument"
        data = {
            "chat_id": MOVIES_CHANNEL_ID,
            "caption": caption,
            "parse_mode": "HTML"
        }
        with open(srt_path, "rb") as f:
            resp = requests.post(url, data=data, files={"document": f}, timeout=120)
            
        result = resp.json()
        if result.get("ok"):
            doc = result["result"].get("document", {})
            return doc.get("file_id")
        else:
            print(f"❌ Subtitle upload error: {result}", flush=True)
        return None
    except Exception as e:
        logger.error(f"Failed to upload subtitle document: {e}")
        return None

def get_file_download_url(file_id: str) -> Optional[str]:
    """Retrieves direct Telegram CDN download / streaming URL from file_id"""
    try:
        url = f"{TELEGRAM_API_BASE}/getFile?file_id={file_id}"
        resp = requests.get(url, timeout=25)
        result = resp.json()
        if result.get("ok"):
            file_path = result["result"]["file_path"]
            return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        return None
    except Exception as e:
        logger.error(f"Failed to get file path: {e}")
        return None
