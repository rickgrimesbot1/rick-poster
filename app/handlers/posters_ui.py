import html
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from app.config import TMDB_API_KEY
from app.state import track_user
from app.utils import download_bytes
from io import BytesIO

async def posters_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Usage:\n/posters movie name [year]")
        return
    try:
        url = "https://api.themoviedb.org/3/search/movie"
        params = {"api_key": TMDB_API_KEY, "query": query, "page": 1, "include_adult": "false"}
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            await update.message.reply_text(f"TMDB error: HTTP {r.status_code}")
            return
        data = r.json().get("results", [])[:5]
    except Exception as e:
        await update.message.reply_text(f"❌ TMDB search failed:\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)
        return
    if not data:
        await update.message.reply_text("❌ No results found"); return
    buttons = []
    for m in data:
        title = m.get("title") or m.get("name") or "Unknown"
        year = (m.get("release_date") or "????")[:4]
        mid = m.get("id")
        if not mid: 
            continue
        buttons.append([InlineKeyboardButton(f"{title} ({year})", callback_data=f"poster:select:{mid}")])
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="poster:close")])
    await update.message.reply_text("Select a Movie 👇", reply_markup=InlineKeyboardMarkup(buttons))

async def posters_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = (q.data or "")
    if data == "poster:close":
        try:
            await q.message.delete()
        except Exception:
            pass
        return

    if data.startswith("poster:select:"):
        tmdb_id = data.split(":", 2)[2]
        # Clean UI: remove buttons and show fetching
        try:
            await q.message.edit_reply_markup(reply_markup=None)
            await q.message.edit_text("Fetching poster…")
        except Exception:
            pass

        # Try movie details first
        title, year, poster_url = None, None, None
        try:
            r = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}",
                             params={"api_key": TMDB_API_KEY}, timeout=10)
            if r.status_code == 200:
                d = r.json()
                title = d.get("title") or d.get("name") or "Unknown"
                if d.get("release_date"):
                    year = d["release_date"][:4]
                poster_path = d.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/original{poster_path}" if poster_path else None
            else:
                # Fallback to TV
                r2 = requests.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}",
                                  params={"api_key": TMDB_API_KEY}, timeout=10)
                if r2.status_code == 200:
                    d = r2.json()
                    title = d.get("name") or d.get("title") or "Unknown"
                    if d.get("first_air_date"):
                        year = d["first_air_date"][:4]
                    poster_path = d.get("poster_path")
                    poster_url = f"https://image.tmdb.org/t/p/original{poster_path}" if poster_path else None
        except Exception:
            pass

        caption = f"<b>🎬 {html.escape(title or 'Unknown')} - ({html.escape(year or '????')})</b>"
        sent = False
        if poster_url:
            img = download_bytes(poster_url)
            if img:
                try:
                    bio = BytesIO(img); bio.name = "poster.jpg"
                    await q.message.chat.send_photo(photo=bio, caption=caption, parse_mode=ParseMode.HTML)
                    sent = True
                except Exception:
                    sent = False
        if not sent:
            await q.message.chat.send_message(text=caption, parse_mode=ParseMode.HTML)

        # Finally, delete the "Select a Movie" message to keep chat clean
        try:
            await q.message.delete()
        except Exception:
            pass
