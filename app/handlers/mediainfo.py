import asyncio
import html
import logging
import os
import re
from os import path as ospath
from shlex import split
from typing import Optional, Tuple

import aiofiles
import aiohttp
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Working dir for temp files
WORKDIR = "mediainfo"

# Tunables (env-overridable) — supports very large files via partial range probing
HEADER_BYTES = int(os.getenv("MI_HEADER_BYTES", str(48 * 1024 * 1024)))  # 48MB
TAIL_BYTES = int(os.getenv("MI_TAIL_BYTES", str(48 * 1024 * 1024)))      # 48MB
TG_MAX_DOWNLOAD = int(os.getenv("MI_TG_MAX_DOWNLOAD", str(120 * 1024 * 1024)))  # 120MB

SECTION_EMOJI = {"General": "🗒", "Video": "🎞", "Audio": "🔊", "Text": "🔠", "Menu": "🗃"}


def _ensure_workdir() -> None:
    if not ospath.isdir(WORKDIR):
        os.makedirs(WORKDIR, exist_ok=True)


def _extract_filename_from_url(url: str) -> str:
    m = re.search(r".+/([^/?#]+)", url)
    return m.group(1) if m else "remote.bin"


async def _fetch_head(session: aiohttp.ClientSession, url: str) -> Tuple[int, bool]:
    """
    Return (content_length, accept_ranges) from server response.
    Falls back to GET if HEAD unsupported.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with session.head(url, headers=headers, allow_redirects=True) as resp:
            cl = resp.headers.get("Content-Length")
            ar = resp.headers.get("Accept-Ranges", "")
            return (int(cl) if cl and cl.isdigit() else 0, "bytes" in ar.lower())
    except Exception:
        try:
            async with session.get(url, headers=headers, allow_redirects=True) as resp:
                cl = resp.headers.get("Content-Length")
                ar = resp.headers.get("Accept-Ranges", "")
                return (int(cl) if cl and cl.isdigit() else 0, "bytes" in ar.lower())
        except Exception as e:
            logger.warning(f"_fetch_head failed: {e}")
            return 0, False


async def _download_range(session: aiohttp.ClientSession, url: str, dest_path: str, start: Optional[int], end: Optional[int]) -> int:
    """
    Download a byte range [start, end] inclusive. If start is None, server may treat as suffix range.
    Returns bytes written.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    if start is not None and end is not None:
        headers["Range"] = f"bytes={start}-{end}"
    elif end is not None and start is None:
        headers["Range"] = f"bytes=-{end}"
    elif start is not None and end is None:
        headers["Range"] = f"bytes={start}-"

    written = 0
    async with session.get(url, headers=headers, allow_redirects=True) as resp:
        resp.raise_for_status()
        async with aiofiles.open(dest_path, "wb") as f:
            async for chunk in resp.content.iter_chunked(1024 * 1024):
                await f.write(chunk)
                written += len(chunk)
    return written


async def _download_url_partial(url: str, header_path: str, tail_path: str, header_bytes: int, tail_bytes: int) -> Tuple[int, int, int]:
    """
    For direct URLs:
    - Fetch HEAD (or GET) to learn size/range support.
    - Download HEADER_BYTES from start.
    - If size known and server supports ranges, also download TAIL_BYTES from end.
    Returns (content_length, header_written, tail_written)
    """
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        cl, ranges = await _fetch_head(session, url)
        h_written = await _download_range(session, url, header_path, 0, header_bytes - 1)
        t_written = 0
        if cl and ranges:
            start_tail = max(0, cl - tail_bytes)
            t_written = await _download_range(session, url, tail_path, start_tail, cl - 1)
        return cl, h_written, t_written


async def _download_telegram_partial(update: Update, file, header_path: str, tail_path: str, header_bytes: int, tail_bytes: int) -> Tuple[int, int, int]:
    """
    For Telegram media:
    - If file_size <= TG_MAX_DOWNLOAD, full download to header_path.
    - Otherwise, try to obtain direct CDN link and perform HTTP range requests to get header and tail.
    Returns (content_length, header_written, tail_written)
    """
    bot = update.get_bot()
    tg_file = await bot.get_file(file.file_id)
    size = file.file_size or 0

    if size and size <= TG_MAX_DOWNLOAD:
        await tg_file.download_to_drive(custom_path=header_path)
        return size, size, 0

    # Try direct link (PTB v21: .link)
    url = None
    try:
        url = tg_file.link
    except Exception:
        url = getattr(tg_file, "file_path", None)

    if not url:
        # Last resort: full download (may be slow or fail)
        await tg_file.download_to_drive(custom_path=header_path)
        size = ospath.getsize(header_path)
        return size, size, 0

    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        cl, ranges = await _fetch_head(session, url)
        h_written = await _download_range(session, url, header_path, 0, header_bytes - 1)
        t_written = 0
        if cl and ranges:
            start_tail = max(0, cl - tail_bytes)
            t_written = await _download_range(session, url, tail_path, start_tail, cl - 1)
        return cl or size or (h_written + t_written), h_written, t_written


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
    Telegram HTML-safe formatter:
    - Allowed tags: b, i, u, s, code, pre, a, blockquote, br
    - Avoid unsupported tags like h1–h6
    """
    header = f"<b>📌 {html.escape(file_name)}</b>\n\n"
    if not stdout.strip():
        return header + "<i>No MediaInfo output.</i>"

    size_line = f"File size                                 : {size_bytes / (1024 * 1024):.2f} MiB"
    body = []
    in_pre = False

    def open_pre():
        nonlocal in_pre
        if not in_pre:
            body.append("<pre>")
            in_pre = True

    def close_pre():
        nonlocal in_pre
        if in_pre:
            body.append("</pre>\n")
            in_pre = False

    for raw_line in stdout.splitlines():
        line = raw_line
        if raw_line.startswith("File size"):
            line = size_line

        # Section headers
        is_section = False
        for section, emoji in SECTION_EMOJI.items():
            if raw_line.startswith(section):
                is_section = True
                close_pre()
                # Section title (bold) — replace 'Text' with 'Subtitle'
                title = html.escape(raw_line.replace("Text", "Subtitle"))
                body.append(f"<b>{emoji} {title}</b>\n")
                open_pre()
                break

        if not is_section:
            open_pre()
            body.append(html.escape(line) + "\n")

    close_pre()
    return header + "".join(body)


async def mi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /mi — Generate MediaInfo for replied media or a direct URL.
    Partial-range probing supports very large files (hundreds of GB) without full download.
    """
    msg = update.message
    if not msg:
        return

    _ensure_workdir()

    # Determine input
    replied = msg.reply_to_message
    url: Optional[str] = None
    media = None

    if context.args:
        url = context.args[0].strip()
    elif replied and replied.text:
        m = re.search(r"https?://\S+", replied.text)
        if m:
            url = m.group(0)

    if not url and replied:
        media = next((i for i in [replied.document, replied.video, replied.audio, replied.voice, replied.animation, replied.video_note] if i is not None), None)

    help_msg = (
        "<b>By replying to media:</b>\n"
        "<code>/mi</code>\n\n"
        "<b>By sending a download link:</b>\n"
        "<code>/mi &lt;link&gt;</code>"
    )

    if not url and not media:
        await msg.reply_text(help_msg, parse_mode=ParseMode.HTML)
        return

    status = await msg.reply_text("<i>Generating MediaInfo...</i>", parse_mode=ParseMode.HTML)

    # Paths
    header_path = ""
    tail_path = ""
    concat_path = ""
    file_name = ""
    size_bytes = 0

    try:
        if url:
            file_name = _extract_filename_from_url(url)
            header_path = ospath.join(WORKDIR, f"hdr_{file_name}")
            tail_path = ospath.join(WORKDIR, f"tail_{file_name}")
            concat_path = ospath.join(WORKDIR, f"probe_{file_name}")

            cl, h_written, t_written = await _download_url_partial(url, header_path, tail_path, HEADER_BYTES, TAIL_BYTES)
            size_bytes = cl or h_written

        else:
            # Telegram media
            file_name = media.file_name or "telegram_media.bin"
            header_path = ospath.join(WORKDIR, f"hdr_{file_name}")
            tail_path = ospath.join(WORKDIR, f"tail_{file_name}")
            concat_path = ospath.join(WORKDIR, f"probe_{file_name}")

            cl, h_written, t_written = await _download_telegram_partial(update, media, header_path, tail_path, HEADER_BYTES, TAIL_BYTES)
            size_bytes = cl or h_written

        # Try mediainfo on header
        stdout_header = await _run_mediainfo(header_path)
        html_header = _format_mediainfo_html(stdout_header, size_bytes, file_name)
        good_header = any(s in stdout_header for s in ("Audio", "Video"))

        # Tail probe if header insufficient and tail exists
        html_tail = ""
        stdout_tail = ""
        good_tail = False
        if (not good_header) and t_written and ospath.exists(tail_path) and ospath.getsize(tail_path) > 0:
            stdout_tail = await _run_mediainfo(tail_path)
            html_tail = _format_mediainfo_html(stdout_tail, size_bytes, file_name)
            good_tail = any(s in stdout_tail for s in ("Audio", "Video"))

        # Concatenate header + tail if needed
        if good_header:
            final_html = html_header
        elif good_tail:
            final_html = html_tail
        else:
            async with aiofiles.open(concat_path, "wb") as out:
                if ospath.exists(header_path):
                    async with aiofiles.open(header_path, "rb") as f:
                        await out.write(await f.read())
                if ospath.exists(tail_path):
                    async with aiofiles.open(tail_path, "rb") as f:
                        await out.write(await f.read())

            stdout_combo = await _run_mediainfo(concat_path)
            final_html = _format_mediainfo_html(stdout_combo, size_bytes, file_name)
            if not stdout_combo.strip():
                final_html = html_header

        # Send result (chunk if very long)
        MAX_LEN = 3500
        if len(final_html) <= MAX_LEN:
            await status.edit_text(final_html, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
        else:
            await status.delete()
            parts = [final_html[i : i + MAX_LEN] for i in range(0, len(final_html), MAX_LEN)]
            for part in parts:
                await msg.reply_text(part, parse_mode=ParseMode.HTML, disable_web_page_preview=False)

    except Exception as e:
        logger.exception("MediaInfo generation failed")
        txt = f"❌ MediaInfo failed:\n<code>{html.escape(str(e))}</code>"
        try:
            await status.edit_text(txt, parse_mode=ParseMode.HTML)
        except Exception:
            await msg.reply_text(txt, parse_mode=ParseMode.HTML)
    finally:
        # Cleanup
        for p in (header_path, tail_path, concat_path):
            try:
                if p and ospath.exists(p):
                    os.remove(p)
            except Exception:
                pass
