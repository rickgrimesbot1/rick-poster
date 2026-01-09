import html
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.config import TMDB_API_KEY
from app.state import track_user
from app.utils import download_bytes
from app.services.tmdb import LANG_MAP

TMDB_IMG = "https://image.tmdb.org/t/p/original"

def _lang_label(code: Optional[str]) -> str:
    if not code:
        return "No Language"
    code = code.lower()
    name = LANG_MAP.get(code)
    if name:
        return f"{name} ({code})"
    return code.upper()

def _tmdb_details(tmdb_id: str) -> Tuple[str, str, str]:
    """
    Returns (ctype, title, year) where ctype is 'movie' or 'tv'.
    Tries movie first, then tv.
    """
    # Movie
    try:
        r = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}",
                         params={"api_key": TMDB_API_KEY}, timeout=10)
        if r.status_code == 200:
            d = r.json()
            title = d.get("title") or d.get("name") or "Unknown"
            year = d.get("release_date")[:4] if d.get("release_date") else "????"
            return "movie", title, year
    except Exception:
        pass
    # TV
    try:
        r = requests.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}",
                         params={"api_key": TMDB_API_KEY}, timeout=10)
        if r.status_code == 200:
            d = r.json()
            title = d.get("name") or d.get("title") or "Unknown"
            year = d.get("first_air_date")[:4] if d.get("first_air_date") else "????"
            return "tv", title, year
    except Exception:
        pass
    return "movie", "Unknown", "????"

def _tmdb_images(tmdb_id: str, ctype: str) -> Dict[str, List[dict]]:
    """
    Fetch images for the given id and content type.
    Returns dict with keys 'backdrops' and 'posters'.
    """
    data = {"backdrops": [], "posters": []}
    try:
        r = requests.get(f"https://api.themoviedb.org/3/{ctype}/{tmdb_id}/images",
                         params={"api_key": TMDB_API_KEY, "include_image_language": "en,null"}, timeout=10)
        if r.status_code == 200:
            js = r.json() or {}
            data["backdrops"] = js.get("backdrops") or []
            data["posters"] = js.get("posters") or []
    except Exception:
        pass
    return data

def _build_language_keyboard(items: List[dict], ctype: str, tmdb_id: str, imgtype: str) -> InlineKeyboardMarkup:
    """
    Build a language selection keyboard from images list.
    Always include 'No Language' button.
    """
    # Count languages
    counts: Dict[str, int] = {}
    for it in items:
        code = it.get("iso_639_1")
        if not code or code in ("", "xx"):
            code_key = "none"
        else:
            code_key = code.lower()
        counts[code_key] = counts.get(code_key, 0) + 1

    # Ensure 'none' button exists even if not present
    if "none" not in counts:
        counts["none"] = 0

    # Sort: put 'none' first, then alphabetically
    keys = [k for k in counts.keys() if k != "none"]
    keys.sort()
    ordered = ["none"] + keys

    buttons: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []

    for k in ordered:
        label = _lang_label(None if k == "none" else k)
        if counts.get(k):
            label = f"{label} ({counts[k]})"
        cb = f"poster:lang:{ctype}:{tmdb_id}:{imgtype}:{k}"
        row.append(InlineKeyboardButton(label, callback_data=cb))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # Navigation
    buttons.append([
        InlineKeyboardButton("⬅ Back", callback_data=f"poster:type:{ctype}:{tmdb_id}:menu"),
        InlineKeyboardButton("❌ Close", callback_data="poster:close"),
    ])
    return InlineKeyboardMarkup(buttons)

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
        data = r.json().get("results", [])[:8]
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

    # Close the UI
    if data == "poster:close":
        try:
            await q.message.delete()
        except Exception:
            pass
        return

    # Step 1: user selected a movie — choose type
    if data.startswith("poster:select:"):
        tmdb_id = data.split(":", 2)[2]
        ctype, title, year = _tmdb_details(tmdb_id)
        caption = f"Selected: <b>{html.escape(title)} ({html.escape(year)})</b>\nChoose image type:"
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Landscape", callback_data=f"poster:type:{ctype}:{tmdb_id}:backdrop"),
                InlineKeyboardButton("Portrait", callback_data=f"poster:type:{ctype}:{tmdb_id}:poster"),
            ],
            [InlineKeyboardButton("❌ Close", callback_data="poster:close")],
        ])
        try:
            await q.message.edit_text(caption, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            try:
                await q.message.reply_text(caption, parse_mode=ParseMode.HTML, reply_markup=kb)
            except Exception:
                pass
        return

    # Step 2: user chose type — list languages
    # Either: poster:type:<ctype>:<id>:backdrop|poster
    if data.startswith("poster:type:"):
        parts = data.split(":")
        # poster:type:<ctype>:<id>:<imgtype or 'menu'>
        if len(parts) < 5:
            return
        ctype = parts[2]
        tmdb_id = parts[3]
        imgtype = parts[4]

        if imgtype == "menu":
            # When coming back from language selection, show type menu again
            _, title, year = _tmdb_details(tmdb_id)
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Landscape", callback_data=f"poster:type:{ctype}:{tmdb_id}:backdrop"),
                    InlineKeyboardButton("Portrait", callback_data=f"poster:type:{ctype}:{tmdb_id}:poster"),
                ],
                [InlineKeyboardButton("❌ Close", callback_data="poster:close")],
            ])
            try:
                await q.message.edit_text(
                    f"Selected: <b>{html.escape(title)} ({html.escape(year)})</b>\nChoose image type:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb
                )
            except Exception:
                pass
            return

        images = _tmdb_images(tmdb_id, ctype)
        items = images.get("backdrops" if imgtype == "backdrop" else "posters") or []

        if not items:
            try:
                await q.message.edit_text("❌ No images found for this type.", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅ Back", callback_data=f"poster:type:{ctype}:{tmdb_id}:menu")],
                    [InlineKeyboardButton("❌ Close", callback_data="poster:close")],
                ]))
            except Exception:
                pass
            return

        ctype_, title, year = _tmdb_details(tmdb_id)
        header = f"<b>{html.escape(title)} ({html.escape(year)})</b>\nChoose a language:"
        kb = _build_language_keyboard(items, ctype, tmdb_id, imgtype)
        try:
            await q.message.edit_text(header, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
        return

    # Step 3: user selected a language — send the image
    # poster:lang:<ctype>:<id>:<imgtype>:<langcode or 'none'>
    if data.startswith("poster:lang:"):
        parts = data.split(":")
        if len(parts) < 6:
            return
        ctype = parts[2]
        tmdb_id = parts[3]
        imgtype = parts[4]
        langkey = parts[5]  # e.g., 'en' or 'none'

        details = _tmdb_details(tmdb_id)
        _, title, year = details

        images = _tmdb_images(tmdb_id, ctype)
        items = images.get("backdrops" if imgtype == "backdrop" else "posters") or []

        chosen = None
        if langkey == "none":
            for it in items:
                code = it.get("iso_639_1")
                if not code or code in ("", "xx"):
                    chosen = it
                    break
        else:
            for it in items:
                if (it.get("iso_639_1") or "").lower() == langkey.lower():
                    chosen = it
                    break

        if not chosen and items:
            chosen = items[0]

        if not chosen or not chosen.get("file_path"):
            try:
                await q.message.edit_text("❌ Could not pick an image.", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅ Back", callback_data=f"poster:type:{ctype}:{tmdb_id}:menu")],
                    [InlineKeyboardButton("❌ Close", callback_data="poster:close")],
                ]))
            except Exception:
                pass
            return

        url = f"{TMDB_IMG}{chosen['file_path']}"
        caption = f"<b>🎬 {html.escape(title)} - ({html.escape(year)})</b>"
        img = download_bytes(url)
        if img:
            try:
                bio = BytesIO(img); bio.name = "poster.jpg"
                await q.message.chat.send_photo(photo=bio, caption=caption, parse_mode=ParseMode.HTML)
            except Exception:
                await q.message.chat.send_message(text=caption, parse_mode=ParseMode.HTML)
        else:
            await q.message.chat.send_message(text=caption, parse_mode=ParseMode.HTML)

        # Clean up the selection message
        try:
            await q.message.delete()
        except Exception:
            pass

        return
