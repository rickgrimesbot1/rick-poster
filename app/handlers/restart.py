import os
import asyncio
from threading import Timer
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from app.config import OWNER_ID
from app.state import mark_pending_restart, clear_pending_restart, PENDING_RESTART

# Utility: owner check helper
def _is_owner(user_id: int | None) -> bool:
    return bool(user_id) and int(user_id) == int(OWNER_ID or 0)

# /whoami — show your Telegram user id (to set OWNER_ID correctly)
async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    await update.message.reply_text(f"Your Telegram user id: {user.id}")

# /restart command (owner only)
async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not _is_owner(user.id):
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Yes", callback_data="restart:yes"),
         InlineKeyboardButton("No", callback_data="restart:no")]
    ])
    await update.message.reply_text("Are you really sure you want to restart the bot ?", reply_markup=kb)

# Callback for Yes/No
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
        try:
            await q.message.edit_reply_markup(reply_markup=None)
            await q.message.edit_text("Restarting...")
        except Exception:
            pass

        # Persist where to announce after restart
        chat_id = q.message.chat.id
        mark_pending_restart(chat_id)

        # Use a threads-based timer to exit regardless of event loop state
        def _hard_exit():
            os._exit(0)

        Timer(1.0, _hard_exit).start()

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

async def _announce_restart_direct(bot):
    pr = PENDING_RESTART
    if not pr or not pr.get("chat_id"):
        return
    chat_id = int(pr["chat_id"])
    message = _build_restart_message()
    try:
        await bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML)
    finally:
        clear_pending_restart()

# Attach a post_init hook so we schedule the announce after the loop is running
def attach_post_init(builder):
    async def _post_init(app):
        async def _delay_and_send():
            await asyncio.sleep(1.0)
            await _announce_restart_direct(app.bot)
        app.create_task(_delay_and_send())
    builder.post_init(_post_init)
