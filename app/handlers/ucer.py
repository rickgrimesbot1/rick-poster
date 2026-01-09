import html
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from app.keyboards import ucer_main_kb, ucer_sub_kb
from app.state import UCER_SETTINGS, save_state, track_user

def _sanitize_index_url(u: str) -> str | None:
    import urllib.parse
    try:
        u = u.strip()
        if not u:
            return None
        p = urllib.parse.urlparse(u)
        if p.scheme not in ("http", "https"):
            return None
        path = p.path or ""
        base = f"{p.scheme}://{p.netloc}"
        if "/0:" not in path:
            return base + "/0:/"
        if not path.endswith("/"):
            path = path + "/"
        out = f"{base}{path}"
        if p.query:
            out += "?" + p.query
        return out
    except Exception:
        return None

def _get_indexes(user_id: int):
    cfg = UCER_SETTINGS.setdefault(user_id, {"gdflix": None, "indexes": [], "full_name": False, "audio_format": False})
    if "indexes" not in cfg: cfg["indexes"] = []
    cfg["indexes"] = (cfg.get("indexes") or [])[:6]
    return cfg["indexes"]

async def ucer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)
    user = update.effective_user
    cfg = UCER_SETTINGS.setdefault(user.id, {"gdflix": None, "indexes": [], "full_name": False, "audio_format": False})
    idx_count = len(cfg.get("indexes") or [])
    await update.message.reply_text(
        "<b>⚙️ UCER SETTINGS</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=ucer_main_kb(cfg.get("full_name", False), cfg.get("audio_format", False), idx_count)
    )

async def ucer_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    cfg = UCER_SETTINGS.setdefault(user_id, {"gdflix": None, "indexes": [], "full_name": False, "audio_format": False})
    action = q.data.split(":")[1]

    if action == "close":
        try: await q.message.delete()
        except Exception: pass
        return

    if action == "back":
        idx_count = len(cfg.get("indexes") or [])
        await q.message.edit_text("<b>⚙️ UCER SETTINGS</b>", parse_mode=ParseMode.HTML,
                                  reply_markup=ucer_main_kb(cfg.get("full_name", False), cfg.get("audio_format", False), idx_count))
        return

    if action == "fullname":
        cfg["full_name"] = not cfg.get("full_name", False); save_state()
        idx_count = len(cfg.get("indexes") or [])
        await q.message.edit_reply_markup(reply_markup=ucer_main_kb(cfg.get("full_name", False), cfg.get("audio_format", False), idx_count))
        return

    if action == "audiofmt":
        cfg["audio_format"] = not cfg.get("audio_format", False); save_state()
        idx_count = len(cfg.get("indexes") or [])
        await q.message.edit_reply_markup(reply_markup=ucer_main_kb(cfg.get("full_name", False), cfg.get("audio_format", False), idx_count))
        return

    if action == "gdflix":
        context.user_data["ucer_edit"] = "gdflix"
        current = cfg.get("gdflix") or "Not Set"
        await q.message.edit_text(f"<b>GDFLIX SETTINGS</b>\n\n<b>Current:</b>\n<code>{current}</code>", parse_mode=ParseMode.HTML, reply_markup=ucer_sub_kb())
        return

    if action == "indexes":
        context.user_data["ucer_edit"] = "indexes"
        idxs = _get_indexes(user_id)
        current = "Not Set" if not idxs else "\n".join(f"{i+1}. {x}" for i, x in enumerate(idxs))
        await q.message.edit_text("<b>INDEX URLs (up to 6)</b>\n\n<b>Current:</b>\n<code>{}</code>".format(html.escape(current)), parse_mode=ParseMode.HTML, reply_markup=ucer_sub_kb())
        return

    if action == "add":
        field = context.user_data.get("ucer_edit")
        if field == "gdflix":
            await q.message.edit_text("<b>Send GDFLIX API KEY now</b>", parse_mode=ParseMode.HTML)
            context.user_data["waiting_ucer"] = "gdflix"
            return
        elif field == "indexes":
            await q.message.edit_text(
                "<b>Send up to 6 Index URLs</b>\n- One per line OR space-separated\n- Example:\n"
                "<code>https://your.example.workers.dev/0:/NEWRip/\nhttps://your.example.workers.dev/0:/TVRIPs/\nhttps://your.example.workers.dev/0:/WEB-DL/</code>",
                parse_mode=ParseMode.HTML
            )
            context.user_data["waiting_ucer"] = "indexes_add"
            return
        else:
            await q.message.edit_text("<b>No field selected to edit.</b>", parse_mode=ParseMode.HTML)
            return

async def ucer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)
    if "waiting_ucer" not in context.user_data:
        return
    user_id = update.effective_user.id
    field = context.user_data.pop("waiting_ucer")
    raw_value = (update.message.text or "").strip()
    cfg = UCER_SETTINGS.setdefault(user_id, {"gdflix": None, "indexes": [], "full_name": False, "audio_format": False})

    if field == "gdflix":
        cfg["gdflix"] = raw_value; save_state()
        msg = await update.message.reply_text("<b>✅ GDFLIX Saved</b>", parse_mode=ParseMode.HTML)
    elif field == "indexes_add":
        candidates = []
        for line in raw_value.replace("\t", " ").splitlines():
            for p in line.strip().split():
                candidates.append(p.strip())
        cleaned = []
        seen = set()
        for u in candidates:
            s = _sanitize_index_url(u)
            if s and s not in seen:
                seen.add(s)
                cleaned.append(s)
        if not cleaned:
            msg = await update.message.reply_text("<b>❌ No valid index URLs found.</b>", parse_mode=ParseMode.HTML)
        else:
            merged = []
            for u in (cfg.get("indexes") or []) + cleaned:
                if u not in merged:
                    merged.append(u)
            cfg["indexes"] = merged[:6]; save_state()
            current = "Not Set" if not cfg["indexes"] else "\n".join(f"{i+1}. {x}" for i, x in enumerate(cfg["indexes"]))
            msg = await update.message.reply_text("<b>✅ Index URLs Saved</b>\n\n<b>Current:</b>\n<code>{}</code>".format(html.escape(current)), parse_mode=ParseMode.HTML)
    else:
        msg = await update.message.reply_text("<b>❌ Unknown UCER field.</b>", parse_mode=ParseMode.HTML)

    try:
        from asyncio import sleep
        await sleep(1.5)
        await msg.delete()
        await update.message.delete()
    except Exception:
        pass