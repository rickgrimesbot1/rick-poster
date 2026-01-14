import html
import logging
import re
import urllib.parse
from io import BytesIO
from typing import Optional

import requests
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Allowed direct image extensions
DIRECT_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif")

# Simple downloader (fallback if your project doesn't already have one)
def download_poster_bytes(url: str, timeout: int = 25) -> Optional[bytes]:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return r.content
    except Exception as e:
        logger.warning(f"download_poster_bytes failed for {url}: {e}")
        return None

def _is_direct_image_link(url: str) -> bool:
    url_low = url.lower()
    return any(url_low.endswith(ext) for ext in DIRECT_IMAGE_EXTS)

def _first_url(text: str | None) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"https?://[^\s<>'\"]+", text)
    return m.group(0) if m else None

# NOTE: The following helpers are assumed to exist in your project.
# If they are in different modules, import them accordingly.
# - track_user(user_id: int)
# - make_full_bold(caption: str) -> str
# - _transform_audio_block_to_ucer(caption: str, user_id: int) -> str
try:
    from app.handlers.core import track_user  # adjust if different location
except Exception:  # pragma: no cover
    def track_user(user_id: int):  # fallback no-op
        logger.debug(f"track_user noop for {user_id}")

try:
    from app.handlers.utils import make_full_bold  # adjust if you keep it elsewhere
except Exception:  # pragma: no cover
    def make_full_bold(text: str) -> str:
        # naive fallback: wrap every non-empty line in <b>...</b>
        lines = [(f"<b>{html.escape(l)}</b>" if l.strip() else l) for l in (text or "").splitlines()]
        return "\n".join(lines)

try:
    from app.handlers.ucer import transform_audio_block as _transform_audio_block_to_ucer  # adjust if needed
except Exception:  # pragma: no cover
    def _transform_audio_block_to_ucer(text: str, user_id: int) -> str:
        # fallback: no transform
        return text

async def rk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /rk behavior as requested:

    1) /rk <streaming link>
       - Must be used as a reply to a /get post (to reuse the SAME caption).
       - Detect platform via API map, fetch LANDSCAPE poster via API, download and post.
       - Caption = replied message caption transformed to FULL BOLD (+ UCER audio transform if enabled in your implementation).

    2) /rk <direct image link>
       - Direct TMDB/PNG/JPG/WEBP/AVIF link.
       - Download the image bytes and post as photo.
       - If used as a reply to a /get post, reuse the SAME caption (FULL BOLD + UCER).

    3) If used with no args:
       - Enforce reply usage and show usage text.
    """
    track_user(update.effective_user.id)
    msg = update.message

    # Must have args or reply (we require args per your original flow)
    if not context.args:
        await msg.reply_text("❌ Usage:\n/rk <streaming link | direct image link>\n\nTip: Reply to your /get post to reuse the same caption.")
        return

    # Parse the target URL from args
    target = context.args[0].strip()

    # If reply exists, try to reuse its caption
    replied = msg.reply_to_message
    raw_caption = (replied.caption or replied.text) if replied else None
    base_caption = ""
    if raw_caption:
        # FULL BOLD caption
        base_caption = make_full_bold(raw_caption)
        # Apply UCER audio transform if enabled in your UCER module
        try:
            base_caption = _transform_audio_block_to_ucer(base_caption, update.effective_user.id)
        except Exception as e:
            logger.warning(f"/rk audio transform failed: {e}")

    # 1) Direct image flow (jpg/png/webp/avif, including TMDB image URLs)
    if _is_direct_image_link(target):
        status = await msg.reply_text("⬇️ Downloading image...")
        poster_bytes = download_poster_bytes(target)
        if not poster_bytes:
            await status.edit_text("❌ Could not download the image.")
            return

        bio = BytesIO(poster_bytes)
        bio.name = "poster.jpg"
        try:
            await status.delete()
        except Exception:
            pass

        # If we had a replied caption, reuse it; otherwise, send without caption
        if base_caption:
            await (replied.reply_photo if replied else msg.reply_photo)(
                photo=bio, caption=base_caption, parse_mode=ParseMode.HTML
            )
        else:
            await (replied.reply_photo if replied else msg.reply_photo)(
                photo=bio
            )
        return

    # 2) Streaming flow via API map
    encoded = urllib.parse.quote_plus(target)
    # Expandable API map
    api_map = {
        "netflix.com":      f"https://nf.rickgrimesapi.workers.dev/?url={encoded}",
        "primevideo.com":   f"https://amzn.rickheroko.workers.dev/?url={encoded}",
        "sunnxt.com":       f"https://snxt.rickgrimesapi.workers.dev/?url={encoded}",
        "zee5.com":         f"https://zee5.rickheroko.workers.dev/?url={encoded}",
        "aha.video":        f"https://aha.rickgrimesapi.workers.dev/?url={encoded}",
        "manoramamax.com":  f"https://mmax.rickgrimesapi.workers.dev/?url={encoded}",
        "viki.com":         f"https://viki.rickheroko.workers.dev/?url={encoded}",
        "iq.com":           f"https://iq.rickgrimesapi.workers.dev/?url={encoded}",
        "hbomax.com":       f"https://hbomax.rickgrimesapi.workers.dev/?url={encoded}",
        "apple.com":        f"https://appletv.rickheroko.workers.dev/?url={encoded}",
        "disneyplus.com":   f"https://dsnp.rickgrimesapi.workers.dev/?url={encoded}",
        "ultraplay":        f"https://ultraplay.rickgrimesapi.workers.dev/?url={encoded}",
        "sonyliv":          f"https://sonyliv.rickheroko.workers.dev/?url={encoded}",
        "hulu":             f"https://hulu.ottposters.workers.dev/?url={encoded}",
    }

    api_url = None
    for key, api in api_map.items():
        if key in target:
            api_url = api
            break

    if not api_url:
        await msg.reply_text("❌ Unsupported streaming platform or not a direct image link.")
        return

    status = await msg.reply_text("🔍 Fetching streaming poster...")

    # Request JSON from the worker and extract landscape
    try:
        r = requests.get(api_url, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        await status.edit_text(f"❌ API error\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)
        return

    # Common keys for landscape/backdrop
    landscape = (
        data.get("landscape")
        or data.get("backdrop")
        or data.get("horizontal")
        or data.get("image")
        or data.get("url")
    )

    if not landscape or not _is_direct_image_link(str(landscape)):
        # Try resolving nested structures
        if isinstance(data, dict):
            for k in ("images", "backdrops", "results", "data"):
                v = data.get(k)
                if isinstance(v, list):
                    for it in v:
                        if isinstance(it, str) and _is_direct_image_link(it):
                            landscape = it; break
                        if isinstance(it, dict):
                            for kk in ("landscape", "backdrop", "horizontal", "image", "url", "file_path"):
                                x = it.get(kk)
                                if isinstance(x, str) and _is_direct_image_link(x):
                                    landscape = x; break
                        if landscape:
                            break
                if landscape:
                    break

    if not landscape:
        await status.edit_text("❌ Landscape poster not found")
        return

    poster_bytes = download_poster_bytes(landscape)
    if not poster_bytes:
        await status.edit_text("❌ Poster download failed")
        return

    bio = BytesIO(poster_bytes)
    bio.name = "streaming_landscape.jpg"

    try:
        await status.delete()
    except Exception:
        pass

    # Send with SAME caption (FULL BOLD + UCER) if replying to a /get post
    if base_caption:
        await (replied.reply_photo if replied else msg.reply_photo)(
            photo=bio,
            caption=base_caption,
            parse_mode=ParseMode.HTML
        )
    else:
        await (replied.reply_photo if replied else msg.reply_photo)(photo=bio)
