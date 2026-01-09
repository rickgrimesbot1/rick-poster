# Minimal posters UI search (optional). You can extend to full language/type/page like your earlier code.
import html
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from app.config import TMDB_API_KEY
from app.state import track_user

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
        if not mid: continue
        buttons.append([InlineKeyboardButton(f"{title} ({year})", callback_data=f"poster:select:{mid}")])
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="poster:close")])
    await update.message.reply_text("Select a Movie 👇", reply_markup=InlineKeyboardMarkup(buttons))