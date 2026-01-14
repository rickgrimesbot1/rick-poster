import html
import logging
import re
import urllib.parse
from io import BytesIO
from typing import Optional, Tuple

import aiohttp
from bs4 import BeautifulSoup
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

TMDB_IMG_ORIGIN = "https://image.tmdb.org"
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
    timeout = aiohttp.ClientTimeout(total=14)
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

async def _fetch_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    try:
        async with session.get(url) as r:
            if r.status != 200:
                return None
            return await r.text()
    except Exception as e:
        logger.warning(f"_fetch_text failed for {url}: {e}")
        return None

# ---------- URL helpers ----------
def _image_ext_from_url(url: str) -> str:
    # Handle querystrings like ".jpg?x=y"
    path = urllib.parse.urlparse(url).path or url
    ext = path.lower().rsplit(".", 1)
    return f".{ext[-1]}" if len(ext) > 1 else ""

def _is_direct_image_link(url: str) -> bool:
    return _image_ext_from_url(url) in DIRECT_IMAGE_EXTS

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

def _to_absolute_image_url(candidate: str, base: Optional[str] = None) -> str:
    """
    Normalize various image URL shapes to absolute HTTP(S).
    - //image.tmdb.org/... → https:...
    - /t/p/original/... or /w780/... → https://image.tmdb.org + path
    - relative starting '/' with page base → urljoin(base, candidate)
    - already absolute → return as is
    """
    if not candidate:
        return candidate
    c = candidate.strip()

    if c.startswith("//"):
        return "https:" + c

    # TMDB path variants
    if c.startswith("/t/") or c.startswith("/p/") or c.startswith("/original") or re.match(r"^/w\d+/", c):
        return urllib.parse.urljoin(TMDB_IMG_ORIGIN, c)

    if c.startswith("/"):
        if base:
            return urllib.parse.urljoin(base, c)
        # fallback assume tmdb
        return urllib.parse.urljoin(TMDB_IMG_ORIGIN, c)

    return c

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
    "max.com":          "https://hbomax.rickgrimesapi.workers.dev/?url={encoded}",
    "apple.com":        "https://appletv.rickheroko.workers.dev/?url={encoded}",
    "disneyplus.com":   "https://dsnp.rickgrimesapi.workers.dev/?url={encoded}",
    "hotstar.com":      "https://dsnp.rickgrimesapi.workers.dev/?url={encoded}",
    "ultraplay":        "https://ultraplay.rickgrimesapi.workers.dev/?url={encoded}",
    "sonyliv.com":      "https://sonyliv.rickheroko.workers.dev/?url={encoded}",
    "sonyliv":          "https://sonyliv.rickheroko.workers.dev/?url={encoded}",
    "hulu":             "https://hulu.ottposters.workers.dev/?url={encoded}",
}

def _pick_stream_api(target_url: str) -> Optional[str]:
    enc = urllib.parse.quote_plus(target_url)
    t = target_url.lower()
    for key, tpl in STREAM_API_MAP_TEMPLATES.items():
        if key in t:
            return tpl.format(encoded=enc)
    return None

def _parse_landscape_from_json(data: dict | list) -> Optional[str]:
    if not isinstance(data, (dict, list)):
        return None

    keys_primary = ("landscape", "backdrop", "horizontal", "image", "url", "poster_landscape", "backdrop_path")
    keys_arrays = ("images", "backdrops", "results", "data")

    def pick_from_obj(obj: dict) -> Optional[str]:
        for k in keys_primary:
            v = obj.get(k)
            if isinstance(v, str) and _is_direct_image_link(v):
                return v
            if isinstance(v, str) and v.startswith("/"):  # relative (TMDB etc.)
                if _is_direct_image_link(v):
                    return v
        # Common nested formats
        v = obj.get("file_path")
        if isinstance(v, str) and (v.startswith("/") or _is_direct_image_link(v)):
            return v
        return None

    if isinstance(data, dict):
        got = pick_from_obj(data)
        if got:
            return got
        for k in keys_arrays:
            arr = data.get(k)
            if isinstance(arr, list):
                for it in arr:
                    if isinstance(it, str) and (_is_direct_image_link(it) or it.startswith("/")):
                        return it
                    if isinstance(it, dict):
                        g = pick_from_obj(it)
                        if g:
                            return g
    else:  # list
        for it in data:
            if isinstance(it, str) and (_is_direct_image_link(it) or it.startswith("/")):
                return it
            if isinstance(it, dict):
                g = pick_from_obj(it)
                if g:
                    return g
    return None

async def _resolve_og_image(session: aiohttp.ClientSession, page_url: str) -> Tuple[Optional[str], Optional[str]]:
    html_text = await _fetch_text(session, page_url)
    if not html_text:
        return None, None
    soup = BeautifulSoup(html_text, "html.parser")
    image = None
    for key in ("og:image", "twitter:image", "og:image:url"):
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            image = tag["content"].strip()
            break
    if image:
        image = _to_absolute_image_url(image, base=page_url)
    title = None
    for key in ("og:title", "twitter:title"):
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            title = tag["content"].strip()
            break
    if not title and soup.title and soup.title.text:
        title = soup.title.text.strip()
    return image, title

async def _resolve_streaming_landscape(session: aiohttp.ClientSession, target_url: str) -> Optional[str]:
    cache: dict = getattr(session, "_rk_cache", {})
    cached = cache.get(target_url)
    if cached:
        return cached

    api_url = _pick_stream_api(target_url)
    landscape = None

    if api_url:
        data = await _fetch_json(session, api_url)
        if data:
            candidate = _parse_landscape_from_json(data)
            if candidate:
                landscape = _to_absolute_image_url(candidate)

    # OG fallback if API didn’t return
    if not landscape:
        og_img, _ = await _resolve_og_image(session, target_url)
        if og_img:
            landscape = og_img

    if landscape:
        cache[target_url] = landscape
        setattr(session, "_rk_cache", cache)
    return landscape

# ---------- Audio block styling ----------
def _wrap_audio_block_in_blockquote(html_caption: str) -> str:
    """
    Wrap the 'Audio Tracks:' section as a single blockquote with each line bold.
    Example result:
    <blockquote>
    <b>🔈 Audio Tracks:</b>
    <b>DDP | 5.1 | 640 kb/s | Korean</b>
    <b>DDP | 5.1 | 640 kb/s | English</b>
    </blockquote>
    """
    if not html_caption:
        return html_caption

    # Match the line that contains "Audio Tracks:"
    m = re.search(r'(?im)^\s*(?:<b>)?[^<]*audio\s*tracks\s*:\s*(?:</b>)?.*$', html_caption)
    if not m:
        return html_caption

    start_line_idx = m.start()
    audio_segment = html_caption[start_line_idx:].strip()

    # Stop block at first double newline after the audio section, if present
    split_idx = audio_segment.find("\n\n")
    if split_idx != -1:
        audio_block = audio_segment[:split_idx]
        rest = audio_segment[split_idx + 2 :]
    else:
        audio_block = audio_segment
        rest = ""

    # Avoid double wrap
    if audio_block.startswith("<blockquote>"):
        return html_caption

    # Bold every non-empty line
    lines = [l for l in audio_block.splitlines() if l.strip()]
    styled = []
    for l in lines:
        s = l.strip()
        if not (s.startswith("<b>") and s.endswith("</b>")):
            s = f"<b>{s}</b>"
        styled.append(s)
    quoted = "<blockquote>\n" + "\n".join(styled) + "\n</blockquote>"

    rebuilt = html_caption[:start_line_idx] + quoted
    if rest:
        rebuilt += "\n\n" + rest
    return rebuilt

# ---------- Command ----------
async def rk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /rk:
    - /rk <streaming link> → resolve LANDSCAPE image via worker API; fallback to OG image if needed.
    - /rk <direct image link> → download and upload (supports TMDB paths and querystrings).
    - When replying to a /get post, reuse SAME caption (FULL BOLD + UCER), with Audio section as quoted bold block.
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
        caption = _wrap_audio_block_in_blockquote(caption)

    session = _ensure_session(context)

    # Direct image link flow (supports TMDB relative path too)
    if _is_direct_image_link(target) or target.startswith("/"):
        abs_url = _to_absolute_image_url(target)
        status = await msg.reply_text("⬇️ Downloading image...")
        img_bytes = await _download_bytes(session, abs_url)
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
