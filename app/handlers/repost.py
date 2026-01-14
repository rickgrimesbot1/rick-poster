import html
import logging
import re
import urllib.parse
from io import BytesIO
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup  # kept if you extend later
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

DIRECT_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif")

# ---------- Caption helpers assumed in your project ----------
try:
    from app.handlers.core import track_user
except Exception:
    def track_user(user_id: int):
        logger.debug(f"track_user noop for {user_id}")

try:
    from app.handlers.utils import make_full_bold
except Exception:
    def make_full_bold(text: str) -> str:
        lines = [(f"<b>{html.escape(l)}</b>" if l.strip() else l) for l in (text or "").splitlines()]
        return "\n".join(lines)

try:
    from app.handlers.ucer import transform_audio_block as _transform_audio_block_to_ucer
except Exception:
    def _transform_audio_block_to_ucer(text: str, user_id: int) -> str:
        return text

# ---------- Async HTTP session management ----------
def _ensure_session(context: ContextTypes.DEFAULT_TYPE) -> aiohttp.ClientSession:
    session: Optional[aiohttp.ClientSession] = context.bot_data.get("_aiohttp_session")
    if session and not session.closed:
        return session
    timeout = aiohttp.ClientTimeout(total=12)
    connector = aiohttp.TCPConnector(limit=50, enable_cleanup_closed=True)
    session = aiohttp.ClientSession(timeout=timeout, connector=connector, headers={"User-Agent": "Mozilla/5.0"})
    context.bot_data["_aiohttp_session"] = session
    return session

async def _download_bytes(session: aiohttp.ClientSession, url: str) -> Optional[bytes]:
    try:
        async with session.get(url) as r:
            if r.status != 200:
                return None
            return await r.read()
    except Exception as e:
        logger.warning(f"_download_bytes failed for {url}: {e}")
        return None

async def _fetch_json(session: aiohttp.ClientSession, url: str) -> Optional[dict | list]:
    try:
        async with session.get(url) as r:
            if r.status != 200:
                return None
            return await r.json(content_type=None)
    except Exception as e:
        logger.warning(f"_fetch_json failed for {url}: {e}")
        return None

# ---------- URL helpers ----------
def _is_direct_image_link(url: str) -> bool:
    u = url.lower()
    return any(u.endswith(ext) for ext in DIRECT_IMAGE_EXTS)

def _extract_urls(text: str | None) -> list[str]:
    if not text:
        return []
    urls = re.findall(r"""<a\s+href=['"]([^'"]+)['"]""", text, flags=re.IGNORECASE)
    urls += re.findall(r"""https?://[^\s<>'"]+""", text)
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            out.append(u); seen.add(u)
    return out

# ---------- Streaming resolution ----------
STREAM_API_MAP_TEMPLATES = {
    "netflix.com":      "https://nf.rickgrimesapi.workers.dev/?url={encoded}",
    "primevideo.com":   "https://amzn.rickheroko.workers.dev/?url={encoded}",
    "sunnxt.com":       "https://snxt.rickgrimesapi.workers.dev/?url={encoded}",
    "zee5.com":         "https://zee5.rickheroko.workers.dev/?url={encoded}",
    "aha.video":        "https://aha.rickgrimesapi.workers.dev/?url={encoded}",
    "manoramamax.com":  "https://mmax.rickgrimesapi.workers.dev/?url={encoded}",
    "viki.com":         "https://viki.rickheroko.workers.dev/?url={encoded}",
    "iq.com":           "https://iq.rickgrimesapi.workers.dev/?url={encoded}",
    "hbomax.com":       "https://hbomax.rickgrimesapi.workers.dev/?url={encoded}",
    "apple.com":        "https://appletv.rickheroko.workers.dev/?url={encoded}",
    "disneyplus.com":   "https://dsnp.rickgrimesapi.workers.dev/?url={encoded}",
    "ultraplay":        "https://ultraplay.rickgrimesapi.workers.dev/?url={encoded}",
    "sonyliv":          "https://sonyliv.rickheroko.workers.dev/?url={encoded}",
    "hulu":             "https://hulu.ottposters.workers.dev/?url={encoded}",
}

def _pick_stream_api(target_url: str) -> Optional[str]:
    enc = urllib.parse.quote_plus(target_url)
    for key, tpl in STREAM_API_MAP_TEMPLATES.items():
        if key in target_url:
            return tpl.format(encoded=enc)
    return None

def _parse_landscape_from_json(data: dict | list) -> Optional[str]:
    if not isinstance(data, (dict, list)):
        return None
    if isinstance(data, dict):
        for k in ("landscape", "backdrop", "horizontal", "image", "url"):
            v = data.get(k)
            if isinstance(v, str) and _is_direct_image_link(v):
                return v
        for k in ("images", "backdrops", "results", "data"):
            arr = data.get(k)
            if isinstance(arr, list):
                for it in arr:
                    if isinstance(it, str) and _is_direct_image_link(it):
                        return it
                    if isinstance(it, dict):
                        for kk in ("landscape", "backdrop", "horizontal", "image", "url", "file_path"):
                            vv = it.get(kk)
                            if isinstance(vv, str) and _is_direct_image_link(vv):
                                return vv
    else:  # list
        for it in data:
            if isinstance(it, str) and _is_direct_image_link(it):
                return it
            if isinstance(it, dict):
                for kk in ("landscape", "backdrop", "horizontal", "image", "url", "file_path"):
                    vv = it.get(kk)
                    if isinstance(vv, str) and _is_direct_image_link(vv):
                        return vv
    return None

async def _resolve_streaming_landscape(session: aiohttp.ClientSession, target_url: str) -> Optional[str]:
    cache: dict = getattr(session, "_rk_cache", {})
    cached = cache.get(target_url)
    if cached:
        return cached
    api_url = _pick_stream_api(target_url)
    if not api_url:
        return None
    data = await _fetch_json(session, api_url)
    if not data:
        return None
    landscape = _parse_landscape_from_json(data)
    if landscape:
        cache[target_url] = landscape
        setattr(session, "_rk_cache", cache)
    return landscape

# ---------- Audio block styling ----------
def _wrap_audio_block_in_blockquote(html_caption: str) -> str:
    """
    Find the 'Audio Tracks:' section (often appended at the end) and wrap the whole block
    from its heading to the end-of-caption into a single quoted bold block.

    Result example:
    <blockquote>
    <b>🔈 Audio Tracks:</b>
    <b>DDP | 5.1 | 640 kb/s | Korean</b>
    <b>DDP | 5.1 | 640 kb/s | English</b>
    </blockquote>
    """
    if not html_caption:
        return html_caption

    # Find the start index of the audio heading (works whether it's within <b>...</b> or plain)
    m = re.search(r'(?is)(audio\s*tracks\s*:)', html_caption)
    if not m:
        return html_caption

    start_idx = m.start()
    # Expand to the beginning of that line
    line_start = html_caption.rfind("\n", 0, start_idx)
    if line_start == -1:
        line_start = 0
    else:
        line_start += 1  # move past the newline

    audio_segment = html_caption[line_start:].strip()
    # Avoid double-wrapping: if already inside a blockquote, keep as is
    if audio_segment.startswith("<blockquote>"):
        return html_caption

    # Ensure each line is bold; if already bold, keep it
    lines = audio_segment.splitlines()
    styled_lines: list[str] = []
    for l in lines:
        s = l.strip()
        if not s:
            continue
        if s.lower().startswith("</blockquote>"):
            # defensive
            continue
        if not (s.startswith("<b>") and s.endswith("</b>")):
            s = f"<b>{s}</b>"
        styled_lines.append(s)

    quoted = "<blockquote>\n" + "\n".join(styled_lines) + "\n</blockquote>"
    return html_caption[:line_start] + quoted

# ---------- Command ----------
async def rk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fast /rk:
    - /rk <streaming link> → fetch landscape via worker API (async) and upload.
    - /rk <direct image link> → download and upload bytes.
    - When replying to a /get post, reuse the SAME caption (FULL BOLD + UCER transform).
    - Audio block is rendered as a single quoted bold block.
    """
    track_user(update.effective_user.id)
    msg = update.message
    if not msg:
        return

    if not context.args:
        await msg.reply_text("❌ Usage:\n/rk <streaming link | direct image link>\n\nTip: Reply to your /get post to reuse the same caption.")
        return

    target = context.args[0].strip()
    replied = msg.reply_to_message

    # Build caption from replied message (if present)
    raw_caption = (replied.caption or replied.text) if replied else None
    caption = ""
    if raw_caption:
        caption = make_full_bold(raw_caption)
        try:
            caption = _transform_audio_block_to_ucer(caption, update.effective_user.id)
        except Exception as e:
            logger.warning(f"/rk audio transform failed: {e}")
        # Ensure requested styling for Audio block
        caption = _wrap_audio_block_in_blockquote(caption)

    session = _ensure_session(context)

    # Direct image link flow
    if _is_direct_image_link(target):
        status = await msg.reply_text("⬇️ Downloading image...")
        img_bytes = await _download_bytes(session, target)
        if not img_bytes:
            await status.edit_text("❌ Could not download the image.")
            return
        bio = BytesIO(img_bytes); bio.name = "poster.jpg"
        try:
            await status.delete()
        except Exception:
            pass
        if caption:
            await (replied.reply_photo if replied else msg.reply_photo)(photo=bio, caption=caption, parse_mode=ParseMode.HTML)
        else:
            await (replied.reply_photo if replied else msg.reply_photo)(photo=bio)
        return

    # Streaming link flow
    status = await msg.reply_text("🔍 Fetching streaming poster...")
    landscape = await _resolve_streaming_landscape(session, target)
    if not landscape or not _is_direct_image_link(landscape):
        await status.edit_text("❌ Landscape poster not found or unsupported platform.")
        return

    img_bytes = await _download_bytes(session, landscape)
    if not img_bytes:
        await status.edit_text("❌ Poster download failed")
        return

    bio = BytesIO(img_bytes); bio.name = "streaming_landscape.jpg"
    try:
        await status.delete()
    except Exception:
        pass
    if caption:
        await (replied.reply_photo if replied else msg.reply_photo)(photo=bio, caption=caption, parse_mode=ParseMode.HTML)
    else:
        await (replied.reply_photo if replied else msg.reply_photo)(photo=bio)

# Backwards-compat alias
async def rk_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await rk(update, context)
