import os
import re
import logging
from typing import Optional, Tuple
from fastapi import Request, HTTPException, Response
from fastapi.responses import StreamingResponse
from telethon import TelegramClient

logger = logging.getLogger("telegram_streamer")

API_ID = int(os.environ.get("TELEGRAM_API_ID", "2040"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "b18441a1ff607e10a989891a5462e627")
BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "8784845752:AAFSX0fkHyALs79xgp8RNs9LExV9LeLyBQs")
MOVIES_CHANNEL = os.environ.get("MOVIES_CHANNEL") or "cinestream_lk"

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

async def resolve_target_video_message(client: TelegramClient, message_id: int):
    """
    Finds the requested message, or gracefully discovers the latest video message in the channel.
    """
    # 1. Resolve channel entity by username or id
    try:
        entity = await client.get_entity("cinestream_lk")
    except Exception:
        try:
            entity = await client.get_entity(int(MOVIES_CHANNEL))
        except Exception as e:
            logger.error(f"Cannot resolve channel {MOVIES_CHANNEL}: {e}")
            raise HTTPException(status_code=500, detail=f"Channel resolution failed: {e}")

    # 2. Try specific message_id if provided
    if message_id > 0:
        try:
            m = await client.get_messages(entity, ids=message_id)
            if m and m.media and (m.video or (m.file and "video" in (m.file.mime_type or ""))):
                return m
            elif m and m.media:
                return m
        except Exception as e:
            logger.warning(f"Error checking message id {message_id}: {e}")

    # 3. Fallback: Search latest video messages in channel
    logger.info("Auto-discovering latest video message in channel...")
    async for m in client.iter_messages(entity, limit=40):
        if m and m.media:
            # Check if video document
            is_vid = bool(m.video or (m.file and "video" in (m.file.mime_type or "")))
            if is_vid:
                logger.info(f"Discovered movie video in message id: {m.id}, size: {m.file.size}")
                return m

    # 4. Fallback: any media
    async for m in client.iter_messages(entity, limit=10):
        if m and m.media:
            return m

    return None

async def list_channel_videos_info(limit: int = 20):
    client = await get_telegram_client()
    try:
        entity = await client.get_entity("cinestream_lk")
    except Exception:
        entity = await client.get_entity(int(MOVIES_CHANNEL))

    results = []
    async for m in client.iter_messages(entity, limit=limit):
        if m and m.media:
            results.append({
                "id": m.id,
                "text": m.message or "",
                "file_name": m.file.name if m.file else None,
                "file_size": m.file.size if m.file else 0,
                "mime_type": m.file.mime_type if m.file else None,
                "is_video": bool(m.video or (m.file and "video" in (m.file.mime_type or "")))
            })
    return results

async def stream_telegram_video_response(message_id: int, request: Request):
    """
    Streams large video file directly from Telegram Channel
    via MTProto chunk streaming with full HTTP Range (206 Partial Content) support.
    """
    client = await get_telegram_client()
    msg = await resolve_target_video_message(client, message_id)

    if not msg or not msg.media or not msg.file:
        raise HTTPException(status_code=404, detail=f"No video file found in channel")

    file_size = msg.file.size
    mime_type = msg.file.mime_type or "video/mp4"
    file_name = msg.file.name or f"movie_{msg.id}.mp4"

    range_header = request.headers.get("range")
    start, end = parse_range_header(range_header, file_size)
    content_length = end - start + 1
    chunk_size = 512 * 1024 # 512 KB chunks

    # Handle HEAD request
    if request.method == "HEAD":
        return Response(
            status_code=200,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Content-Type": mime_type,
                "Access-Control-Allow-Origin": "*",
            },
            media_type=mime_type
        )

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
            logger.warning(f"Streaming chunk notice for msg {msg.id}: {err}")

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
