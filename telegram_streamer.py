import os
import re
import logging
from typing import Optional, Tuple
from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse
from telethon import TelegramClient

logger = logging.getLogger("telegram_streamer")

API_ID = int(os.environ.get("TELEGRAM_API_ID", "2040"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "b18441a1ff607e10a989891a5462e627")
BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "8784845752:AAFSX0fkHyALs79xgp8RNs9LExV9LeLyBQs")
MOVIES_CHANNEL = int(os.environ.get("MOVIES_CHANNEL") or os.environ.get("MOVIES_CHANNEL_ID", "-1003984700777"))

_client: Optional[TelegramClient] = None

async def get_telegram_client() -> TelegramClient:
    global _client
    if _client is None:
        _client = TelegramClient('cinestream_stream_session', API_ID, API_HASH)
        await _client.start(bot_token=BOT_TOKEN)
        logger.info("✅ Telethon MTProto Streaming Client connected successfully!")
    elif not _client.is_connected():
        await _client.connect()
    return _client

def parse_range_header(range_header: Optional[str], file_size: int) -> Tuple[int, int]:
    """Parses standard HTTP Range header (e.g., 'bytes=0-1048575' or 'bytes=50000-')"""
    if not range_header or not range_header.startswith("bytes="):
        return 0, file_size - 1

    range_val = range_header.replace("bytes=", "").strip()
    parts = range_val.split("-")
    start = int(parts[0]) if parts[0] else 0
    end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1

    start = max(0, min(start, file_size - 1))
    end = max(start, min(end, file_size - 1))
    return start, end

async def stream_telegram_video_response(message_id: int, request: Request, channel_id: int = MOVIES_CHANNEL):
    """
    Streams large video file (> 20MB, up to 2GB) directly from Telegram Channel
    via MTProto chunk streaming with full HTTP Range (206 Partial Content) support.
    Solves Telegram's 'Media is too big' web limitation!
    """
    client = await get_telegram_client()
    try:
        msg = await client.get_messages(channel_id, ids=message_id)
    except Exception as e:
        logger.error(f"Failed to fetch Telegram message {message_id}: {e}")
        raise HTTPException(status_code=404, detail=f"Message {message_id} not found: {e}")

    if not msg or not msg.media:
        raise HTTPException(status_code=404, detail=f"No media found in message {message_id}")

    file_size = msg.file.size
    mime_type = msg.file.mime_type or "video/mp4"
    file_name = msg.file.name or f"movie_{message_id}.mp4"

    range_header = request.headers.get("range")
    start, end = parse_range_header(range_header, file_size)
    content_length = end - start + 1
    chunk_size = 512 * 1024 # 512 KB chunks for smooth playback

    async def video_chunk_generator():
        try:
            async for chunk in client.iter_download(
                msg.media,
                offset=start,
                limit=content_length,
                chunk_size=chunk_size,
                request_size=chunk_size
            ):
                yield chunk
        except Exception as err:
            logger.warning(f"Streaming chunk notice for msg {message_id}: {err}")

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Type": mime_type,
        "Content-Disposition": f'inline; filename="{file_name}"',
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Range, Content-Range, Accept-Ranges, Content-Type",
        "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges, Content-Length",
        "Cache-Control": "public, max-age=3600"
    }

    status_code = 206 if range_header else 200
    return StreamingResponse(
        video_chunk_generator(),
        status_code=status_code,
        headers=headers,
        media_type=mime_type
    )
