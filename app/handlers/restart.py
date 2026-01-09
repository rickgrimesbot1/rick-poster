import os
from threading import Timer
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from app.config import OWNER_ID

def _is_owner(user_id: int | None) -> bool:
    return bool(user_id) and int(user_id) == int(OWNER_ID or 0)

def _build_restart_message() -> str:
    now = datetime.now().astimezone()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    tzname = now.tzname() or "UTC"
    return (
        f"<b>⌬ Restarted Successfully!</b>\n"
        f"<b>┟ Date: {date_str}</b>\n"
        f"<b>┠ Time: {time_str}</b>\n"
        f"<b>┠ TimeZone: {tzname}</b>\n"
        f"<b>┖ Version: RickV1</b>"
    )

# /whoami — help set OWNER_ID
async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        await update.message.reply_text(f"Your Telegram user id: {user.id}")

# /restart (owner only) → Yes/No prompt
async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not _is_owner(user.id):
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Yes", callback_data="restart:yes"),
         InlineKeyboardButton("No", callback_data="restart:no")]
    ])
    await update.message.reply_text("Are you really sure you want to restart the bot ?", reply_markup=kb)

# Callback
async def restart_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user
    if not user or not _is_owner(user.id):
        try:
            await q.message.delete()
        except Exception:
            pass
        return

    action = (q.data or "").split(":", 1)[1] if ":" in (q.data or "") else ""
    if action == "no":
        try:
            await q.message.edit_reply_markup(reply_markup=None)
            await q.message.edit_text("Cancelled.")
        except Exception:
            pass
        return

    if action == "yes":
        # Show restarting
        try:
            await q.message.edit_reply_markup(reply_markup=None)
            await q.message.edit_text("Restarting...")
        except Exception:
            pass

        # Send success block immediately (pre-exit) in same chat
        try:
            msg = _build_restart_message()
            await q.message.chat.send_message(text=msg, parse_mode=ParseMode.HTML)
        except Exception:
            pass

        # Hard exit after 1s → Heroku will restart the dyno
        def _hard_exit():
            os._exit(0)

        Timer(1.0, _hard_exit).start()
