import html
import re
import urllib.parse
import requests
from io import BytesIO
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.config import NETFLIX_API
from app.state import track_user
from app.utils import download_bytes, ensure_line_bold

STREAM_APIS = {
    "primevideo.com": "https://amzn.rickheroko.workers.dev/?url={encoded}",
    "sunnxt.com": "https://snxt.rickgrimesapi.workers.dev/?url={encoded}",
    "zee5.com": "https://zee5.rickheroko.workers.dev/?url={encoded}",
    "aha.video": "https://aha.rickgrimesapi.workers.dev/?url={encoded}",
    "manoramamax.com": "https://mmax.rickgrimesapi.workers.dev/?url={encoded}",
    "viki.com": "https://viki.rickheroko.workers.dev/?url={encoded}",
    "iq.com": "https://iq.rickgrimesapi.workers.dev/?url={encoded}",
    "hbomax.com": "https://hbomax.rickgrimesapi.workers.dev/?url={encoded}",
    "apple.com": "https://appletv.rickheroko.workers.dev/?url={encoded}",
    "disneyplus.com": "https://dsnp.rickgrimesapi.workers.dev/?url={encoded}",
    "ultraplay": "https://ultraplay.rickgrimesapi.workers.dev/?url={encoded}",
    "sonyliv": "https://sonyliv.rickheroko.workers.dev/?url={encoded}",
    "hulu": "https://hulu.ottposters.workers.dev/?url={encoded}",
    "wetv": "https://wetv.the-zake.workers.dev/?url={encoded}",
    "bookmyshow": "https://bookmyshow-dcbots.jibinlal232.workers.dev/?url={encoded}",
    "tentkotta": "https://tentkotta.rickheroko.workers.dev/?url={encoded}",
}

async def generic_stream(update: Update, context: ContextTypes.DEFAULT_TYPE, label_landscape: str, label_portrait: str, base_api: str):
    track_user(update.effective_user.id)
    url = " ".join(context.args) if context.args else ""
    if not url:
        # PTB v21: context.command not available; derive command from incoming text
        cmd_text = (update.effective_message.text or "").split()[0] or "/command"
        await update.message.reply_text(f"Usage:\n{cmd_text} <url>")
        return

    encoded = urllib.parse.quote_plus(url)
    api = base_api.format(encoded=encoded)
    msg = await update.message.reply_text("🔍 Fetching...")
    try:
        r = requests.get(api, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        await msg.edit_text(f"❌ Failed:\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)
        return

    title = data.get("title") or data.get("name") or "Unknown"
    year = data.get("year") or data.get("releaseYear") or ""
    portrait = data.get("poster") or data.get("portrait") or data.get("vertical") or data.get("image")
    landscape = data.get("landscape") or data.get("backdrop") or data.get("horizontal") or data.get("cover")

    text = (
        f"<b>{label_landscape} {html.escape(landscape or 'Not Found')}</b>\n\n"
        f"<b>{label_portrait} {html.escape(portrait or 'Not Found')}</b>\n\n"
        f"<b>{html.escape(title)}{(' - (' + str(year) + ')') if year else ''}</b>\n\n"
        "<b><blockquote>Powered By: <a href='https://t.me/ott_posters_club'>Ott Posters Club 🎞️</a></blockquote></b>"
    )
    await msg.edit_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=False)

# Individual command wrappers
async def amzn(update, context):  await generic_stream(update, context, "AMZN Poster:", "Portrait:", STREAM_APIS["primevideo.com"])
async def airtel(update, context):await generic_stream(update, context, "AIRTEL Poster:", "Portrait:", "https://hgbots.vercel.app/bypaas/airtel.php?url={encoded}")
async def zee5(update, context):  await generic_stream(update, context, "ZEE5 Poster:", "Portrait:", STREAM_APIS["zee5.com"])
async def hulu(update, context):  await generic_stream(update, context, "Hulu Poster:", "Cover:", STREAM_APIS["hulu"])
async def viki(update, context):  await generic_stream(update, context, "VIKI Poster:", "Cover:", STREAM_APIS["viki.com"])
async def snxt(update, context):  await generic_stream(update, context, "SNXT Poster:", "Portrait:", STREAM_APIS["sunnxt.com"])
async def mmax(update, context):  await generic_stream(update, context, "ManoramaMax Poster:", "Portrait:", STREAM_APIS["manoramamax.com"])
async def aha(update, context):   await generic_stream(update, context, "Aha Poster:", "Portrait:", STREAM_APIS["aha.video"])
async def dsnp(update, context):  await generic_stream(update, context, "Disney+ Poster:", "Portrait:", STREAM_APIS["disneyplus.com"])
async def apple(update, context): await generic_stream(update, context, "AppleTV Poster:", "Portrait:", STREAM_APIS["apple.com"])
async def bms(update, context):   await generic_stream(update, context, "BookMyShow Poster:", "Portrait:", STREAM_APIS["bookmyshow"])
async def iq(update, context):    await generic_stream(update, context, "iQIYI Poster:", "Portrait:", STREAM_APIS["iq.com"])
async def hbo(update, context):   await generic_stream(update, context, "HBOMAX Poster:", "Portrait:", STREAM_APIS["hbomax.com"])
async def up(update, context):    await generic_stream(update, context, "UltraPlay Poster:", "Portrait:", STREAM_APIS["ultraplay"])
async def uj(update, context):    await generic_stream(update, context, "UltraJhakaas Poster:", "Portrait:", "https://ultrajhakaas.rickheroko.workers.dev/?url={encoded}")
async def wetv(update, context):  await generic_stream(update, context, "WeTv Poster:", "Portrait:", STREAM_APIS["wetv"])
async def sl(update, context):    await generic_stream(update, context, "SonyLiv Poster:", "Portrait:", "https://sonyliv.rickheroko.workers.dev/?url={encoded}")
async def tk(update, context):    await generic_stream(update, context, "TentKotta Poster:", "Portrait:", "https://tentkotta.rickheroko.workers.dev/?url={encoded}")

async def nf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    raw = " ".join(context.args).strip() if context.args else ""
    if not raw:
        await update.message.reply_text("Usage:\n/nf <netflix url or id>")
        return
    movie_id = None
    if raw.startswith("http"):
        m = re.search(r"/title/(\d+)", raw)
        if m: movie_id = m.group(1)
    if not movie_id and re.fullmatch(r"\d+", raw):
        movie_id = raw
    if not movie_id:
        await update.message.reply_text("Could not extract Netflix movie id.")
        return

    api_url = f"{NETFLIX_API}{movie_id}"
    status_msg = await update.message.reply_text("🔍 Fetching Netflix data…")
    try:
        r = requests.get(api_url, timeout=30); r.raise_for_status()
        data = r.json()
    except Exception as e:
        try: await status_msg.delete()
        except Exception: pass
        await update.message.reply_text(f"❌ Netflix API error:\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)
        return

    portrait = data.get("portrait") or data.get("poster")
    landscape = data.get("landscape") or data.get("backdrop")
    title = data.get("title") or data.get("name") or "Unknown"
    year = data.get("year") or data.get("releaseYear") or ""

    esc = lambda v: html.escape(v) if v else "Not Found"
    text = (
        f"<b>Netflix Poster:</b> <b>{esc(landscape)}</b>\n\n"
        f"<b>Portrait:</b> <b><a href='{esc(portrait)}'>Click</a></b>\n\n"
        f"<b>{esc(title)}{(' (' + esc(str(year)) + ')') if year else ''}</b>\n\n"
        "<b><blockquote>Powered By: <a href='https://t.me/ott_posters_club'>Ott Posters Club 🎞️</a></blockquote></b>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=False)

# NEW: /rk — reply-based poster resend with same caption
async def rk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    msg = update.message

    # Must be used as reply
    if not msg.reply_to_message:
        await msg.reply_text("❌ /rk must be used as a reply to a previous captioned message")
        return

    if not context.args:
        await msg.reply_text("❌ Usage:\n/rk <streaming url>")
        return

    stream_url = context.args[0].strip()
    # Base caption from replied message
    base_caption = msg.reply_to_message.caption or msg.reply_to_message.text
    if not base_caption:
        await msg.reply_text("❌ Replied message has no caption")
        return

    # Full boldify (normalize ' - [' to ' [')
    bold_lines = []
    for line in base_caption.splitlines():
        s = re.sub(r"\s*-\s*\[", " [", line)
        bold_lines.append(ensure_line_bold(s) if s.strip() else "")
    final_caption = "\n".join(bold_lines)

    # Detect platform → API
    encoded = urllib.parse.quote_plus(stream_url)
    api_url = None
    for key, templ in STREAM_APIS.items():
        if key in stream_url:
            api_url = templ.format(encoded=encoded)
            break
    # Netflix direct id/url special case
    if not api_url and ("netflix.com" in stream_url or re.fullmatch(r"\d{6,}", stream_url)):
        # Allow `/rk 12345678`
        movie_id = None
        m = re.search(r"/title/(\d+)", stream_url)
        if m:
            movie_id = m.group(1)
        elif re.fullmatch(r"\d+", stream_url):
            movie_id = stream_url
        if movie_id:
            api_url = f"{NETFLIX_API}{movie_id}"

    if not api_url:
        await msg.reply_text("❌ Unsupported or unknown streaming platform URL")
        return

    status = await msg.reply_text("🔍 Fetching streaming poster...")

    try:
        r = requests.get(api_url, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        await status.edit_text(f"❌ API error\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)
        return

    # Landscape poster only
    landscape = data.get("landscape") or data.get("backdrop") or data.get("horizontal") or data.get("cover")
    if not landscape:
        await status.edit_text("❌ Landscape poster not found")
        return

    poster_bytes = download_bytes(landscape)
    if not poster_bytes:
        await status.edit_text("❌ Poster download failed")
        return

    bio = BytesIO(poster_bytes)
    bio.name = "streaming_landscape.jpg"

    try:
        await status.delete()
    except Exception:
        pass

    # Send to the replied message thread with the SAME caption
    await msg.reply_to_message.reply_photo(photo=bio, caption=final_caption, parse_mode=ParseMode.HTML)
