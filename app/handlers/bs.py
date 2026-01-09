import os
import html
from typing import List, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from app.config import OWNER_ID

# Keys to expose/edit via /bs
ENV_KEYS: List[Tuple[str, str]] = [
    ("TELEGRAM_BOT_TOKEN", "Token"),
    ("OWNER_ID", "Owner"),
    ("GDFLIX_API_KEY", "GDFlix API"),
    ("GDFLIX_API_BASE", "GDFlix Base"),
    ("GDFLIX_FILE_BASE", "GDFlix File Base"),
    ("WORKERS_BASE", "Workers Base"),
    ("TMDB_API_KEY", "TMDB API"),
    ("DEV_LINK", "Dev Link"),
    ("START_PHOTO_URL", "Start Photo"),
    ("HELP_PHOTO_URL", "Help Photo"),
    ("NETFLIX_API", "Netflix API"),
    ("FREEIMAGE_API_KEY", "FreeImage API"),
    ("FREEIMAGE_UPLOAD_API", "FreeImage Upload API"),
    ("STATE_REMOTE_URL", "Remote State URL"),
    ("DISABLE_MEDIAINFO", "Disable MediaInfo"),
]

def _is_owner(user_id: int | None) -> bool:
    return bool(user_id) and int(user_id) == int(OWNER_ID or 0)

def _mask_value(key: str, val: str | None) -> str:
    if not val:
        return "Not Set"
    v = str(val).strip()
    # Treat anything with key substrings as secret
    key_l = key.lower()
    if any(s in key_l for s in ("token", "key", "secret")):
        if len(v) <= 6:
            return "******"
        return f"{v[:3]}…{v[-3:]}"
    # Otherwise show as-is but escape
    return html.escape(v)

def _env_value(key: str) -> str:
    return os.environ.get(key, "") or ""

def _write_env_file(key: str, value: str) -> bool:
    """Best-effort write to local .env. Not persistent on Heroku dynos."""
    try:
        path = ".env"
        lines = []
        found = False
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f.readlines():
                    if line.strip().startswith(f"{key}="):
                        lines.append(f"{key}={value}\n")
                        found = True
                    else:
                        lines.append(line)
        if not found:
            lines.append(f"{key}={value}\n")
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception:
        return False

def _menu_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for key, label in ENV_KEYS:
        cb = f"bs:set:{key}"
        row.append(InlineKeyboardButton(f"Set {label}", callback_data=cb))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    # Utility actions
    buttons.append([
        InlineKeyboardButton("🔄 Restart Now", callback_data="bs:restart"),
        InlineKeyboardButton("❌ Close", callback_data="bs:close"),
    ])
    return InlineKeyboardMarkup(buttons)

async def bs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not _is_owner(user.id):
        return
    # Build the current env listing
    lines = ["<b>🛠 Bot Settings (.env)</b>", ""]
    for key, label in ENV_KEYS:
        val = _env_value(key)
        masked = _mask_value(key, val)
        lines.append(f"<b>{html.escape(label)}:</b> <code>{masked}</code>")
    lines.append("")
    lines.append("<b>Select a field to set/update from the buttons below.</b>")
    text = "\n".join(lines)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=_menu_keyboard())

async def bs_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user
    if not user or not _is_owner(user.id):
        try:
            await q.message.delete()
        except Exception:
            pass
        return
    data = q.data or ""
    if data == "bs:close":
        try:
            await q.message.delete()
        except Exception:
            pass
        return
    if data == "bs:restart":
        # Reuse existing restart flow via inline confirmation
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Yes", callback_data="restart:yes"),
             InlineKeyboardButton("No", callback_data="restart:no")]
        ])
        try:
            await q.message.edit_text("Are you really sure you want to restart the bot ?", reply_markup=kb)
        except Exception:
            pass
        return
    if data.startswith("bs:set:"):
        key = data.split(":", 2)[2]
        label = next((lbl for k, lbl in ENV_KEYS if k == key), key)
        current = _env_value(key)
        masked = _mask_value(key, current)
        prompt = (
            f"<b>Set {html.escape(label)}</b>\n\n"
            f"<b>Current:</b> <code>{masked}</code>\n\n"
            f"Send the new value now."
        )
        try:
            await q.message.edit_text(prompt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅ Back", callback_data="bs:back")],
                [InlineKeyboardButton("❌ Close", callback_data="bs:close")],
            ]))
        except Exception:
            pass
        context.user_data["waiting_bs_key"] = key
        return
    if data == "bs:back":
        # Re-render the menu
        lines = ["<b>🛠 Bot Settings (.env)</b>", ""]
        for key, label in ENV_KEYS:
            val = _env_value(key)
            masked = _mask_value(key, val)
            lines.append(f"<b>{html.escape(label)}:</b> <code>{masked}</code>")
        lines.append("")
        lines.append("<b>Select a field to set/update from the buttons below.</b>")
        text = "\n".join(lines)
        try:
            await q.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_menu_keyboard())
        except Exception:
            pass
        return

async def bs_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not _is_owner(user.id):
        return
    key = context.user_data.pop("waiting_bs_key", None)
    if not key:
        return
    new_value = (update.message.text or "").strip()
    if not new_value:
        await update.message.reply_text("❌ Empty value. Send a non-empty value.")
        return
    # Apply to runtime env
    os.environ[key] = new_value
    # Best-effort write to .env (non-persistent on Heroku)
    wrote = _write_env_file(key, new_value)
    note = "Saved to runtime and .env." if wrote else "Saved to runtime. (.env write failed or not available)"
    # Show confirmation + menu again
    lines = [
        f"<b>✅ {html.escape(key)} updated.</b>",
        f"<b>{html.escape(note)}</b>",
        "",
        "<b>Restart the bot to apply changes everywhere.</b>",
    ]
    try:
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Restart Now", callback_data="bs:restart")],
            [InlineKeyboardButton("⬅ Back", callback_data="bs:back"),
             InlineKeyboardButton("❌ Close", callback_data="bs:close")],
        ]))
    except Exception:
        pass
