import os
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from app.config import OWNER_ID
from app.state import mark_pending_restart, clear_pending_restart, PENDING_RESTART

# /restart command (owner only)
async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != OWNER_ID:
        return
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Yes", callback_data="restart:yes"),
            InlineKeyboardButton("No", callback_data="restart:no"),
        ]
    ])
    await update.message.reply_text("Are you really sure you want to restart the bot ?", reply_markup=kb)

# Callback for Yes/No
async def restart_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user
    if not user or user.id != OWNER_ID:
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

        # Give Telegram a moment to send the message, then exit
        async def _delayed_exit():
            await asyncio.sleep(1.0)
            os._exit(0)

        asyncio.create_task(_delayed_exit())

# Job: announce after restart (scheduled from main)
async def _announce_restart_job(context: ContextTypes.DEFAULT_TYPE):
    pr = PENDING_RESTART
    if not pr or not pr.get("chat_id"):
        return
    chat_id = int(pr["chat_id"])
    now = datetime.now().astimezone()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    tzname = now.tzname() or "UTC"

    message = (
        f"<b>⌬ Restarted Successfully!</b>\n"
        f"<b>┟ Date: {date_str}</b>\n"
        f"<b>┠ Time: {time_str}</b>\n"
        f"<b>┠ TimeZone: {tzname}</b>\n"
        f"<b>┖ Version: RickV1</b>"
    )
    try:
        await context.bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML)
    except Exception:
        pass
    finally:
        clear_pending_restart()

def schedule_restart_announce(application):
    # Schedule the announce job shortly after app starts
    application.job_queue.run_once(_announce_restart_job, when=1.0)
