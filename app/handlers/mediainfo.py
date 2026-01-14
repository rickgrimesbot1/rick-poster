import asyncio
import html
import logging
import os
import re
from os import getcwd, path as ospath
from shlex import split
from typing import Optional

import aiofiles
import aiohttp
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Local working directory for temporary files
WORKDIR = "mediainfo"
# Max bytes to download from a remote link for quick probe (~10MB)
REMOTE_PROBE_BYTES = 10 * 1024 * 1024
# Max file size to fully download from Telegram (50MB)
TG_MAX_DOWNLOAD = 50 * 1024 * 1024

SECTION_EMOJI = {"General": "🗒", "Video": "🎞", "Audio": "🔊", "Text": "🔠", "Menu": "🗃"}


def _ensure_workdir() -> None:
    if not ospath.isdir(WORKDIR):
        os.makedirs(WORKDIR, exist_ok=True)


def _extract_filename_from_url(url: str) -> str:
    m = re.search(r".+/([^/?#]+)", url)
    return m.group(1) if m else "remote.bin"


async def _download_url_partial(session: aiohttp.ClientSession, url: str, dest_path: str, max_bytes: int = REMOTE_PROBE_BYTES) -> int:
    """
    Download up to max_bytes from a remote URL into dest_path.
    Returns number of bytes written.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    written = 0
    async with session.get(url, headers=headers) as resp:
        resp.raise_for_status()
        async with aiofiles.open(dest_path, "wb") as f:
            async for chunk in resp.content.iter_chunked(1024 * 1024):
                await f.write(chunk)
                written += len(chunk)
                if written >= max_bytes:
                    break
    return written


async def _download_telegram_file(update: Update, file, dest_path: str, max_bytes: int = TG_MAX_DOWNLOAD) -> int:
    """
    Download a Telegram media file (document/video/audio/voice/animation/video_note).
    Fully downloads if file_size <= max_bytes, else downloads first N chunks (best effort).
    Returns number of bytes written.
    """
    bot = update.get_bot()
    tg_file = await bot.get_file(file.file_id)
    # file_path is a relative path on Telegram's file CDN; use File.download_to_drive for simplicity for small files
    bytes_written = 0

    if (file.file_size or 0) <= max_bytes:
        await tg_file.download_to_drive(custom_path=dest_path)
        return file.file_size or ospath.getsize(dest_path)

    # Large file: stream with aiohttp using the HTTPS URL
    # File.link() returns a direct URL (PTB v21)
    url = tg_file.file_path if hasattr(tg_file, "file_path") else tg_file.file_id
    try:
        url = tg_file.link
    except Exception:
        # Fallback: if PTB can't generate link, just attempt with known base (not always available)
        logger.warning("Could not get direct file link; attempting default download_to_drive()")
        await tg_file.download_to_drive(custom_path=dest_path)
        return ospath.getsize(dest_path)

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            async with aiofiles.open(dest_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    await f.write(chunk)
                    bytes_written += len(chunk)
                    if bytes_written >= max_bytes:
                        break

    return bytes_written


async def _run_mediainfo(file_path: str) -> str:
    """
    Run 'mediainfo' CLI and return stdout.
    """
    proc = await asyncio.create_subprocess_exec(
        *split(f'mediainfo "{file_path}"'),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = (stderr or b"").decode(errors="ignore")
        logger.warning(f"mediainfo exited with {proc.returncode}: {err}")
    return (stdout or b"").decode(errors="ignore")


def _format_mediainfo_html(stdout: str, size_bytes: int, file_name: str) -> str:
    """
    Convert mediainfo plain text output to HTML with section emojis and preformatted blocks.
    """
    header = f"<h4>📌 {html.escape(file_name)}</h4><br><br>"
    if not stdout.strip():
        return header + "<i>No MediaInfo output.</i>"

    # Override File size line with calculated MiB
    size_line = f"File size                                 : {size_bytes / (1024 * 1024):.2f} MiB"
    tc = ""
    trigger = False

    for raw_line in stdout.splitlines():
        line = raw_line
        # Replace file size
        if raw_line.startswith("File size"):
            line = size_line

        # Section headers
        for section, emoji in SECTION_EMOJI.items():
            if raw_line.startswith(section):
                trigger = True
                if not raw_line.startswith("General"):
                    tc += "</pre><br>"
                tc += f"<h4>{emoji} {html.escape(raw_line.replace('Text', 'Subtitle'))}</h4>"
                break

        if trigger:
            tc += "<br><pre>"
            trigger = False
        else:
            tc += html.escape(line) + "\n"

    tc += "</pre><br>"
    return header + tc


async def mi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /mi — Generate MediaInfo for a replied media or a provided direct URL.

    Usage:
    - Reply to media, then send /mi
    - Send /mi <direct URL>
    """
    msg = update.message
    if not msg:
        return

    _ensure_workdir()

    # Determine input: URL via args or media in replied message
    replied = msg.reply_to_message
    url: Optional[str] = None
    media = None

    if context.args:
        url = context.args[0].strip()
    elif replied and replied.text:
        # If replied text is a URL, use it
        m = re.search(r"https?://\S+", replied.text)
        if m:
            url = m.group(0)

    if not url and replied:
        media = next(
            (
                i
                for i in [
                    replied.document,
                    replied.video,
                    replied.audio,
                    replied.voice,
                    replied.animation,
                    replied.video_note,
                ]
                if i is not None
            ),
            None,
        )

    help_msg = (
        "<b>By replying to media:</b>\n"
        "<code>/mi</code>\n\n"
        "<b>By sending a download link:</b>\n"
        "<code>/mi &lt;link&gt;</code>"
    )

    if not url and not media:
        await msg.reply_text(help_msg, parse_mode=ParseMode.HTML)
        return

    # Inform user
    status = await msg.reply_text("<i>Generating MediaInfo...</i>", parse_mode=ParseMode.HTML)

    file_path = ""
    file_size = 0
    try:
        if url:
            file_name = _extract_filename_from_url(url)
            file_path = ospath.join(WORKDIR, file_name)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
                # Try to read content-length; fallback to 0
                async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as head_resp:
                    try:
                        file_size = int(head_resp.headers.get("Content-Length", "0"))
                    except Exception:
                        file_size = 0
                # Download partial
                file_size = file_size or await _download_url_partial(session, url, file_path, REMOTE_PROBE_BYTES)
                if file_size == 0:
                    # If we couldn't determine size, set to downloaded length
                    file_size = ospath.getsize(file_path)

        else:
            # Telegram media
            file_name = media.file_name or "telegram_media.bin"
            file_path = ospath.join(WORKDIR, file_name)
            file_size = media.file_size or 0
            bytes_written = await _download_telegram_file(update, media, file_path, TG_MAX_DOWNLOAD)
            if bytes_written and (file_size == 0 or bytes_written < file_size):
                file_size = bytes_written

        # Run mediainfo
        stdout = await _run_mediainfo(file_path)
        html_out = _format_mediainfo_html(stdout, file_size, ospath.basename(file_path))

        # Try to send. If too long, split into chunks.
        # Telegram limit for HTML messages is large but we chunk at ~4000 chars per part.
        MAX_LEN = 3500
        if len(html_out) <= MAX_LEN:
            await status.edit_text(html_out, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
        else:
            await status.delete()
            parts = [html_out[i : i + MAX_LEN] for i in range(0, len(html_out), MAX_LEN)]
            for i, part in enumerate(parts, 1):
                await msg.reply_text(part, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
    except Exception as e:
        logger.exception("MediaInfo generation failed")
        try:
            await status.edit_text(f"❌ MediaInfo failed:\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)
        except Exception:
            await msg.reply_text(f"❌ MediaInfo failed:\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)
    finally:
        try:
            if file_path and ospath.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
