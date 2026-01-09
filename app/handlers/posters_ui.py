import html
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
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
    return name if name else code.upper()

def _tmdb_details(tmdb_id: str) -> Tuple[str, str, str]:
    """Return (ctype, title, year) where ctype is 'movie' or 'tv'. Try movie first, then tv."""
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
    """Fetch images for the given id and content type. Returns dict with keys 'backdrops' and 'posters'."""
    data = {"backdrops": [], "posters": []}
    try:
        r = requests.get(
            f"https://api.themoviedb.org/3/{ctype}/{tmdb_id}/images",
            params={"api_key": TMDB_API_KEY, "include_image_language": "en,null"},
            timeout=10,
        )
        if r.status_code == 200:
            js = r.json() or {}
            data["backdrops"] = js.get("backdrops") or []
            data["posters"] = js.get("posters") or []
    except Exception:
        pass
    return data

def _filter_items_by_lang(items: List[dict], langkey: str) -> List[dict]:
    """Filter images by language key; 'none' means no/xx/empty language."""
    if not items:
        return []
    if langkey == "none":
        out = []
        for it in items:
            code = it.get("iso_639_1")
            if not code or code in ("", "xx"):
                out.append(it)
        return out or items  # fallback: if empty, use all
    langkey = langkey.lower()
    out = [it for it in items if (it.get("iso_639_1") or "").lower() == langkey]
    return out or items  # fallback

def _build_language_keyboard(items: List[dict], ctype: str, tmdb_id: str, imgtype: str) -> InlineKeyboardMarkup:
    """Build language selection keyboard. Always include 'No Language' button."""
    # Unique language codes
    codes: List[str] = []
    saw_none = False
    for it in items:
        code = it.get("iso_639_1")
        if not code or code in ("", "xx"):
            saw_none = True
        else:
            lc = code.lower()
            if lc not in codes:
                codes.append(lc)

    buttons: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []

    # Always include No Language
    row.append(InlineKeyboardButton("No Language", callback_data=f"poster:lang:{ctype}:{tmdb_id}:{imgtype}:none"))
    if len(row) == 2:
        buttons.append(row); row = []

    for code in sorted(codes):
        label = _lang_label(code)
        cb = f"poster:lang:{ctype}:{tmdb_id}:{imgtype}:{code}"
        row.append(InlineKeyboardButton(label, callback_data=cb))
        if len(row) == 2:
            buttons.append(row); row = []
    if row:
        buttons.append(row)

    # Navigation
    buttons.append([
        InlineKeyboardButton("⬅ Back", callback_data=f"poster:type:{ctype}:{tmdb_id}:menu"),
        InlineKeyboardButton("❌ Close", callback_data="poster:close"),
    ])
    return InlineKeyboardMarkup(buttons)

def _paging_keyboard(total: int, index: int, ctype: str, tmdb_id: str, imgtype: str, langkey: str) -> InlineKeyboardMarkup:
    """Build paging keyboard: << < [i/total] > >> + Back + Close."""
    def cb(i: int) -> str:
        return f"poster:view:{ctype}:{tmdb_id}:{imgtype}:{langkey}:{i}"
    first = InlineKeyboardButton("<<", callback_data=cb(0))
    prev = InlineKeyboardButton("<", callback_data=cb(max(0, index - 1)))
    mid = InlineKeyboardButton(f"{index+1}/{total}", callback_data=cb(index))
    nxt = InlineKeyboardButton(">", callback_data=cb(min(total - 1, index + 1)))
    last = InlineKeyboardButton(">>", callback_data=cb(total - 1))
    nav_row = [first, prev, mid, nxt, last]
    control_row = [
        InlineKeyboardButton("Back", callback_data=f"poster:type:{ctype}:{tmdb_id}:menu"),
        InlineKeyboardButton("Close", callback_data="poster:close"),
    ]
    return InlineKeyboardMarkup([nav_row, control_row])

def _build_caption(title: str, year: str, imgtype: str, lang_name: str, width: int | str, height: int | str, url: str) -> str:
    return (
        f"<b>{html.escape(title)} ({html.escape(year)})</b>\n\n"
        f"<b>• Type : {'Landscape' if imgtype == 'backdrop' else 'Portrait'}</b>\n\n"
        f"<b>• Language: {html.escape(lang_name)}</b>\n\n"
        f"<b>• Width: {html.escape(str(width))}, Height: {html.escape(str(height))}</b>\n\n"
        f"<b>• <a href='{html.escape(url)}'>Click Here</a></b>"
    )

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
    await update.message.reply_text("Search Results :", reply_markup=InlineKeyboardMarkup(buttons))

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
        caption = f"<b>{html.escape(title)} ({html.escape(year)})</b>\n\n<b>Choose image type:</b>"
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
    # poster:type:<ctype>:<id>:backdrop|poster|menu
    if data.startswith("poster:type:"):
        parts = data.split(":")
        if len(parts) < 5:
            return
        ctype = parts[2]
        tmdb_id = parts[3]
        imgtype = parts[4]

        if imgtype == "menu":
            _, title, year = _tmdb_details(tmdb_id)
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Landscape", callback_data=f"poster:type:{ctype}:{tmdb_id}:backdrop"),
                    InlineKeyboardButton("Portrait", callback_data=f"poster:type:{ctype}:{tmdb_id}:poster"),
                ],
                [InlineKeyboardButton("❌ Close", callback_data="poster:close")],
            ])
            try:
                await q.message.edit_text(f"<b>{html.escape(title)} ({html.escape(year)})</b>\n\n<b>Choose image type:</b>",
                                          parse_mode=ParseMode.HTML, reply_markup=kb)
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

        _, title, year = _tmdb_details(tmdb_id)
        header = f"<b>{html.escape(title)} ({html.escape(year)})</b>\n\n<b>Choose a language:</b>"
        kb = _build_language_keyboard(items, ctype, tmdb_id, imgtype)
        try:
            await q.message.edit_text(header, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
        return

    # Step 3: user selected a language — show first image with paging keyboard
    # poster:lang:<ctype>:<id>:<imgtype>:<langcode or 'none'>
    if data.startswith("poster:lang:"):
        parts = data.split(":")
        if len(parts) < 6:
            return
        ctype = parts[2]
        tmdb_id = parts[3]
        imgtype = parts[4]
        langkey = parts[5]

        ctype_, title, year = _tmdb_details(tmdb_id)
        images = _tmdb_images(tmdb_id, ctype)
        full_items = images.get("backdrops" if imgtype == "backdrop" else "posters") or []
        items = _filter_items_by_lang(full_items, langkey)

        if not items:
            try:
                await q.message.edit_text("❌ No images for this language.", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅ Back", callback_data=f"poster:type:{ctype}:{tmdb_id}:menu")],
                    [InlineKeyboardButton("❌ Close", callback_data="poster:close")],
                ]))
            except Exception:
                pass
            return

        index = 0
        chosen = items[index]
        file_path = chosen.get("file_path")
        if not file_path:
            try:
                await q.message.edit_text("❌ Could not pick an image.", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅ Back", callback_data=f"poster:type:{ctype}:{tmdb_id}:menu")],
                    [InlineKeyboardButton("❌ Close", callback_data="poster:close")],
                ]))
            except Exception:
                pass
            return

        url = f"{TMDB_IMG}{file_path}"
        width = chosen.get("width") or "Unknown"
        height = chosen.get("height") or "Unknown"
        lang_name = _lang_label(None if langkey == "none" else langkey)
        caption = _build_caption(title, year, imgtype, lang_name, width, height, url)
        kb = _paging_keyboard(len(items), index, ctype, tmdb_id, imgtype, langkey)

        # Send photo with keyboard, then delete selection message to keep chat clean
        try:
            img = download_bytes(url)
            if img:
                bio = BytesIO(img); bio.name = "poster.jpg"
                sent = await q.message.chat.send_photo(photo=bio, caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                sent = await q.message.chat.send_message(text=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
            try:
                await q.message.delete()
            except Exception:
                pass
        except Exception:
            # fallback: just send caption
            await q.message.chat.send_message(text=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
            try:
                await q.message.delete()
            except Exception:
                pass
        return

    # Paging: poster:view:<ctype>:<id>:<imgtype>:<langkey>:<index>
    if data.startswith("poster:view:"):
        parts = data.split(":")
        if len(parts) < 7:
            return
        ctype = parts[2]
        tmdb_id = parts[3]
        imgtype = parts[4]
        langkey = parts[5]
        try:
            index = int(parts[6])
        except Exception:
            index = 0

        ctype_, title, year = _tmdb_details(tmdb_id)
        images = _tmdb_images(tmdb_id, ctype)
        full_items = images.get("backdrops" if imgtype == "backdrop" else "posters") or []
        items = _filter_items_by_lang(full_items, langkey)

        if not items:
            return

        index = max(0, min(len(items) - 1, index))
        chosen = items[index]
        file_path = chosen.get("file_path")
        if not file_path:
            return
        url = f"{TMDB_IMG}{file_path}"
        width = chosen.get("width") or "Unknown"
        height = chosen.get("height") or "Unknown"
        lang_name = _lang_label(None if langkey == "none" else langkey)
        caption = _build_caption(title, year, imgtype, lang_name, width, height, url)
        kb = _paging_keyboard(len(items), index, ctype, tmdb_id, imgtype, langkey)

        # Try editing the existing message media; if it fails, send a new photo
        try:
            await q.message.edit_media(
                media=InputMediaPhoto(media=url, caption=caption, parse_mode=ParseMode.HTML),
                reply_markup=kb
            )
        except Exception:
            # Fallback: send a new photo and delete old one
            try:
                img = download_bytes(url)
                if img:
                    bio = BytesIO(img); bio.name = "poster.jpg"
                    await q.message.chat.send_photo(photo=bio, caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
                else:
                    await q.message.chat.send_message(text=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
                await q.message.delete()
            except Exception:
                pass
        return
