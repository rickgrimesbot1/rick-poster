import html
import re
from io import BytesIO
import urllib.parse

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.config import OWNER_ID, WORKERS_BASE
from app.services import gdflix
from app.services.mediainfo import get_text_from_url_or_path, parse_audio_block
from app.services.tmdb import extract_title_year_from_filename, strict_match, pick_language, backdrop_from_tmdb_url
from app.state import ALLOWED_USERS, AUTHORIZED_CHATS, UCER_SETTINGS, BOT_CONFIG, track_user, save_state
from app.utils import (
    is_gdrive_link, is_workers_link, extract_drive_id, extract_drive_id_from_workers,
    extract_workers_path, human_readable_size, strip_extension, get_remote_size, download_bytes
)

# ---------- Progress helpers (bold + 10-step bar) ----------
def _progress_bar(percent: int) -> str:
    """
    Return a 10-step bar with filled '▰' and empty '▱' according to percent.
    10% -> ▰▱▱▱▱▱▱▱▱▱
    50% -> ▰▰▰▰▰▱▱▱▱▱
    100% -> ▰▰▰▰▰▰▰▰▰▰
    """
    p = max(0, min(100, percent))
    filled = p // 10
    return "▰" * filled + "▱" * (10 - filled)

def _progress_text(percent: int) -> str:
    return f"<b>Wait :- {percent}%</b>\n<b>{_progress_bar(percent)}</b>"

# ---------- Access helpers ----------
def is_allowed_user(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    if not ALLOWED_USERS:
        return False
    return user_id in ALLOWED_USERS

def is_chat_authorized(update: Update) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False
    if user.id == OWNER_ID:
        return True
    if chat.type in ("group", "supergroup"):
        return chat.id in AUTHORIZED_CHATS
    return is_allowed_user(user.id)

# ---------- Authorization commands ----------
async def authorize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Use /authorize inside the group you want to authorize.")
        return
    if OWNER_ID and user.id != OWNER_ID:
        await update.message.reply_text("Only bot owner can authorize this group.")
        return
    AUTHORIZED_CHATS.add(chat.id)
    save_state()
    await update.message.reply_text("✅ Group authorized.", parse_mode=ParseMode.HTML)

async def allow_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /allow <user_id>")
        return
    try:
        uid = int(context.args[0])
    except Exception:
        await update.message.reply_text("Invalid user id.")
        return
    if uid not in ALLOWED_USERS:
        ALLOWED_USERS.append(uid)
        save_state()
    await update.message.reply_text(f"<b>✅ User {uid} granted full access</b>", parse_mode=ParseMode.HTML)

async def deny_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /deny <user_id>")
        return
    try:
        uid = int(context.args[0])
    except Exception:
        await update.message.reply_text("Invalid user id.")
        return
    if uid in ALLOWED_USERS:
        ALLOWED_USERS.remove(uid)
        save_state()
    await update.message.reply_text(f"<b>❌ User {uid} access revoked</b>", parse_mode=ParseMode.HTML)

# ---------- Workers helpers ----------
def _normalize_workers_base(index_url: str) -> str | None:
    import urllib.parse
    if not index_url: return None
    try:
        p = urllib.parse.urlparse(index_url.strip())
        if not p.scheme or not p.netloc:
            return None
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return None

def _get_user_indexes(user_id: int):
    cfg = UCER_SETTINGS.setdefault(user_id, {"gdflix": None, "indexes": [], "full_name": False, "audio_format": False})
    if "indexes" not in cfg: cfg["indexes"] = []
    cfg["indexes"] = (cfg.get("indexes") or [])[:6]
    return cfg["indexes"]

def workers_link_from_drive_id_for_user(user_id: int, file_id: str) -> str:
    indexes = _get_user_indexes(user_id)
    base = _normalize_workers_base(indexes[0]) if indexes else None
    if not base:
        base = WORKERS_BASE
    return f"{base}/0:findpath?id={file_id}"

def format_filename(name: str, user_id: int) -> str:
    if not name:
        return "Unknown"
    full_on = UCER_SETTINGS.get(user_id, {}).get("full_name", False)
    from app.utils import strip_extension
    return name if full_on else strip_extension(name)

# ---------- /get ----------
async def get_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)
    user = update.effective_user
    if not is_chat_authorized(update):
        await update.message.reply_text("❌ Access denied.\nGroup: need /authorize\nPM: need /allow")
        return

    # GDFLIX mode
    api_key = None
    if not BOT_CONFIG.get("GDFLIX_GLOBAL", True):
        api_key = UCER_SETTINGS.get(user.id, {}).get("gdflix")
        if not api_key:
            await update.message.reply_text("❌ <b>GDFlix is disabled.</b>\n\nAdd your own GDFlix API using /ucer to continue.", parse_mode=ParseMode.HTML)
            return

    if not context.args:
        await update.message.reply_text("Usage:\n/get <one or more links>")
        return

    parts = (update.message.text or "").split()
    urls = [p for p in parts if p.startswith("http")]
    if not urls:
        await update.message.reply_text("No valid links found.")
        return
    if len(urls) > 8:
        await update.message.reply_text("Maximum 8 links allowed in one /get.")
        return

    status_msg = await update.message.reply_text(_progress_text(10), parse_mode=ParseMode.HTML)

    try:
        drive_ids = []
        media_source_url = None
        for url in urls:
            if "download.aspx" in url and media_source_url is None:
                media_source_url = url
            if is_gdrive_link(url):
                did = extract_drive_id(url)
                if did: drive_ids.append(did)
            elif is_workers_link(url):
                did = extract_drive_id_from_workers(url)
                if did:
                    drive_ids.append(did)
                else:
                    wpath = extract_workers_path(url)
                    if wpath and media_source_url is None:
                        media_source_url = wpath

        await status_msg.edit_text(_progress_text(30), parse_mode=ParseMode.HTML)

        items = []
        first_name_for_tmdb = None

        for did in drive_ids:
            gd_res = gdflix.share_file(did, api_key)
            if not gd_res:
                continue
            raw_name = gd_res.get("name") or "Unknown"
            display_name = format_filename(raw_name, user.id)
            size = gd_res.get("size") or 0
            size_str = human_readable_size(size)
            link = gdflix.file_link_from_response(gd_res, did)
            items.append({"id": did, "name": display_name, "size_str": size_str, "size_bytes": size, "link": link})
            if not first_name_for_tmdb:
                first_name_for_tmdb = raw_name

        await status_msg.edit_text(_progress_text(50), parse_mode=ParseMode.HTML)

        if not media_source_url:
            first_drive_id = items[0]["id"] if items else (drive_ids[0] if drive_ids else None)
            if first_drive_id:
                media_source_url = workers_link_from_drive_id_for_user(user.id, first_drive_id)

        parsed_mediainfo = ""
        org_aud_lang = None
        if media_source_url:
            mi_text = get_text_from_url_or_path(media_source_url)
            if mi_text:
                ucer_audio_fmt = UCER_SETTINGS.get(user.id, {}).get("audio_format", False)
                parsed_mediainfo, org_aud_lang = parse_audio_block(mi_text, ucer_audio_fmt)
                if not first_name_for_tmdb:
                    m = re.search(r"Complete name\s*:\s*(.+)", mi_text)
                    if m: first_name_for_tmdb = m.group(1).strip()

        await status_msg.edit_text(_progress_text(70), parse_mode=ParseMode.HTML)

        final_title, final_year, poster_url = "Unknown", "????", None
        if first_name_for_tmdb:
            base_title, file_year = extract_title_year_from_filename(first_name_for_tmdb)
            t_title, t_year, t_lang, poster_url, tmdb_url = strict_match(base_title, file_year)
            final_title = t_title or base_title or "Unknown"
            final_year = t_year or file_year or "????"

        await status_msg.edit_text(_progress_text(90), parse_mode=ParseMode.HTML)

        header = f"<b>🎬 {html.escape(final_title)} - ({html.escape(final_year)})</b>"
        lines = [header, ""]
        for it in items:
            lines.append(f"<b>{html.escape(it['name'])} [{it['size_str']}]</b>")
            lines.append(f"<b>{html.escape(it['link'])}</b>")
            lines.append("")

        if not items and media_source_url:
            from app.utils import strip_extension
            fname = urllib.parse.unquote(urllib.parse.urlparse(media_source_url).path.rsplit("/", 1)[-1])
            display_name = strip_extension(fname)
            size_bytes = get_remote_size(media_source_url)
            size_str = human_readable_size(size_bytes) if size_bytes else "Unknown"
            lines.append(f"<b>{html.escape(display_name)} [{size_str}]</b>")
            lines.append(f"<b>{html.escape(media_source_url)}</b>")
            lines.append("")

        if parsed_mediainfo:
            lines.append(parsed_mediainfo.rstrip())

        msg = "\n".join(lines)

        await status_msg.edit_text(_progress_text(100), parse_mode=ParseMode.HTML)

        try: await status_msg.delete()
        except Exception: pass

        poster_bytes = download_bytes(poster_url) if poster_url else None
        if poster_bytes:
            bio = BytesIO(poster_bytes); bio.name = "poster.jpg"
            await update.message.reply_photo(photo=bio, caption=msg, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    except Exception as e:
        try: await status_msg.delete()
        except Exception: pass
        await update.message.reply_text(f"⚠️ Something went wrong.\n\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)

# ---------- /info ----------
async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)
    user = update.effective_user
    if not is_chat_authorized(update):
        await update.message.reply_text("❌ Access denied.\nGroup: need /authorize\nPM: need /allow")
        return
    if not context.args:
        await update.message.reply_text("Usage:\n/info <direct download link>")
        return
    parts = (update.message.text or "").split()
    urls = [p for p in parts if p.startswith("http")]
    if not urls:
        await update.message.reply_text("No valid link found."); return
    url = urls[0]

    status_msg = await update.message.reply_text(_progress_text(10), parse_mode=ParseMode.HTML)
    try:
        size_bytes = get_remote_size(url)
        await status_msg.edit_text(_progress_text(30), parse_mode=ParseMode.HTML)

        size_str = human_readable_size(size_bytes) if size_bytes else "Unknown"
        mi_text = get_text_from_url_or_path(url)
        if not mi_text:
            try: await status_msg.delete()
            except Exception: pass
            await update.message.reply_text("Could not read media info from this link.")
            return

        ucer_audio_fmt = UCER_SETTINGS.get(user.id, {}).get("audio_format", False)
        parsed_mediainfo, org_aud_lang = parse_audio_block(mi_text, ucer_audio_fmt)

        await status_msg.edit_text(_progress_text(50), parse_mode=ParseMode.HTML)

        filename = urllib.parse.unquote(urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]) or "Unknown"
        base_title, file_year = extract_title_year_from_filename(filename)
        tmdb_title, tmdb_year, tmdb_lang_code, poster_url, tmdb_url = strict_match(base_title, file_year)
        final_title = tmdb_title or base_title or "Unknown"
        final_year = tmdb_year or file_year or "????"

        await status_msg.edit_text(_progress_text(90), parse_mode=ParseMode.HTML)

        header = f"<b>🎬 {html.escape(final_title)} - ({html.escape(final_year)})</b>"
        lines = [header, "", f"<b>{html.escape(base_title)} [{size_str}]</b>", ""]
        if parsed_mediainfo:
            lines.append(parsed_mediainfo.rstrip())
        msg = "\n".join(lines)

        await status_msg.edit_text(_progress_text(100), parse_mode=ParseMode.HTML)
        try: await status_msg.delete()
        except Exception: pass

        poster_bytes = download_bytes(poster_url) if poster_url else None
        if poster_bytes:
            bio = BytesIO(poster_bytes); bio.name = "poster.jpg"
            await update.message.reply_photo(photo=bio, caption=msg, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        try: await status_msg.delete()
        except Exception: pass
        await update.message.reply_text(f"⚠️ /info failed.\n\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)

# ---------- /ls ----------
async def ls_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)
    user = update.effective_user
    if not is_chat_authorized(update):
        await update.message.reply_text("��� Access denied.\nGroup: need /authorize\nPM: need /allow")
        return
    if not context.args:
        await update.message.reply_text("Usage:\n/ls <Google Drive link or workers path>")
        return
    parts = (update.message.text or "").split()
    urls = [p for p in parts if p.startswith("http")]
    if not urls:
        await update.message.reply_text("No valid link found."); return
    url = urls[0]
    if not (is_gdrive_link(url) or is_workers_link(url)):
        await update.message.reply_text("Only Google Drive or workers links are supported for /ls.")
        return

    status_msg = await update.message.reply_text(_progress_text(10), parse_mode=ParseMode.HTML)
    try:
        drive_id, is_workers_path = None, False
        if is_gdrive_link(url):
            drive_id = extract_drive_id(url)
        else:
            drive_id = extract_drive_id_from_workers(url)
            if not drive_id and extract_workers_path(url):
                is_workers_path = True

        await status_msg.edit_text(_progress_text(30), parse_mode=ParseMode.HTML)

        if not drive_id and not is_workers_path:
            try: await status_msg.delete()
            except Exception: pass
            await update.message.reply_text("Could not extract Drive ID from this link.")
            return

        if drive_id:
            gd_res = gdflix.share_file(drive_id, None)
            if not gd_res:
                try: await status_msg.delete()
                except Exception: pass
                await update.message.reply_text("GdFlix did not return any data for this file.")
                return
            raw_name = gd_res.get("name") or "Unknown"
            display_name = strip_extension(raw_name)
            size = gd_res.get("size") or 0
            gdlink = gdflix.file_link_from_response(gd_res, drive_id)
        else:
            gdlink = url
            raw_name = urllib.parse.unquote(urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]) or "Unknown"
            display_name = strip_extension(raw_name)
            size = get_remote_size(url) or 0

        await status_msg.edit_text(_progress_text(50), parse_mode=ParseMode.HTML)

        media_source_url = workers_link_from_drive_id_for_user(user.id, drive_id) if drive_id else url
        mi_text = get_text_from_url_or_path(media_source_url)
        parsed_mediainfo, org_aud_lang = ("", None)
        if mi_text:
            ucer_audio_fmt = UCER_SETTINGS.get(user.id, {}).get("audio_format", False)
            parsed_mediainfo, org_aud_lang = parse_audio_block(mi_text, ucer_audio_fmt)

        await status_msg.edit_text(_progress_text(70), parse_mode=ParseMode.HTML)

        base_title, file_year = extract_title_year_from_filename(raw_name)
        tmdb_title, tmdb_year, tmdb_lang_code, poster_url_unused, tmdb_url = strict_match(base_title, file_year)
        final_title = tmdb_title or base_title or "Unknown"
        final_year = tmdb_year or file_year or "????"

        backdrop_url = backdrop_from_tmdb_url(tmdb_url) if tmdb_url else None

        await status_msg.edit_text(_progress_text(90), parse_mode=ParseMode.HTML)

        header = f"<b>🎬 {html.escape(final_title)} - ({html.escape(final_year)})</b>"
        lines = [header, "", f"<b>{html.escape(display_name)} [{human_readable_size(size)}]</b>", f"<b>{html.escape(gdlink)}</b>", ""]
        if parsed_mediainfo:
            lines.append(parsed_mediainfo.rstrip())
        msg = "\n".join(lines)

        await status_msg.edit_text(_progress_text(100), parse_mode=ParseMode.HTML)
        try: await status_msg.delete()
        except Exception: pass

        poster_bytes = download_bytes(backdrop_url) if backdrop_url else None
        if poster_bytes:
            bio = BytesIO(poster_bytes); bio.name = "backdrop.jpg"
            await update.message.reply_photo(photo=bio, caption=msg, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        try: await status_msg.delete()
        except Exception: pass
        await update.message.reply_text(f"⚠️ /ls failed.\n\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)

# ---------- /tmdb ----------
async def tmdb_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Usage:\n/tmdb Maari 2025 OR a TMDB URL")
        return
    raw = " ".join(context.args).strip()
    poster_url = None
    tmdb_title = None
    tmdb_year = "????"
    try:
        status_msg = await update.message.reply_text(_progress_text(10), parse_mode=ParseMode.HTML)

        if raw.startswith("http") and "themoviedb.org" in raw:
            import re, requests
            from app.config import TMDB_API_KEY
            m = re.search(r"themoviedb\.org/(movie|tv)/(\d+)", raw)
            if not m:
                try: await status_msg.delete()
                except Exception: pass
                await update.message.reply_text("Invalid TMDB URL."); return
            ctype, tmdb_id = m.group(1), m.group(2)
            api_url = f"https://api.themoviedb.org/3/{ctype}/{tmdb_id}"
            r = requests.get(api_url, params={"api_key": TMDB_API_KEY}, timeout=10)
            await status_msg.edit_text(_progress_text(50), parse_mode=ParseMode.HTML)
            if r.status_code != 200:
                try: await status_msg.delete()
                except Exception: pass
                await update.message.reply_text(f"TMDB error: HTTP {r.status_code}")
                return
            data = r.json()
            tmdb_title = data.get("title") or data.get("name") or "Unknown"
            if data.get("release_date"): tmdb_year = data["release_date"][:4]
            elif data.get("first_air_date"): tmdb_year = data["first_air_date"][:4]
            poster_path = data.get("poster_path")
            if poster_path: poster_url = "https://image.tmdb.org/t/p/original" + poster_path
        else:
            title = raw
            import re
            m = re.search(r"(19|20)\d{2}", raw)
            if m:
                year = m.group(0)
                title = raw[:m.start()].strip()
            else:
                year = "????"
            t_title, t_year, t_lang, poster_url, tmdb_url = strict_match(title, year)
            await status_msg.edit_text(_progress_text(70), parse_mode=ParseMode.HTML)
            tmdb_title = t_title or title or "Unknown"
            tmdb_year = t_year or year or "????"

        await status_msg.edit_text(_progress_text(100), parse_mode=ParseMode.HTML)
        try: await status_msg.delete()
        except Exception: pass

        header = f"<b>🎬 {html.escape(tmdb_title)} - ({html.escape(tmdb_year)})</b>"
        poster_bytes = download_bytes(poster_url) if poster_url else None
        if poster_bytes:
            bio = BytesIO(poster_bytes); bio.name = "poster.jpg"
            await update.message.reply_photo(photo=bio, caption=header, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(header, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"⚠️ TMDB lookup failed.\n\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)

# ---------- Manual poster ----------
async def manual_poster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)
    msg = update.message
    if not msg or not msg.photo:
        return
    base = None
    if context.chat_data.get("last_caption"):
        base = context.chat_data["last_caption"]
    elif msg.reply_to_message:
        base = msg.reply_to_message.caption or msg.reply_to_message.text
    if not base:
        await msg.reply_text("First use /tmdb or /get (or send caption) then send poster photo 🙂")
        return
    from app.utils import ensure_line_bold
    lines = []
    for l in base.splitlines():
        s = re.sub(r"\s*-\s*\[", " [", l)
        lines.append(ensure_line_bold(s) if s.strip() else "")
    caption_to_send = "\n".join(lines)
    photo = msg.photo[-1]
    await msg.chat.send_photo(photo=photo.file_id, caption=caption_to_send, parse_mode=ParseMode.HTML)
