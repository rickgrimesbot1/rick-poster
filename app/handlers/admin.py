from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from app.config import OWNER_ID
from app.keyboards import admin_panel_kb
from app.state import BOT_CONFIG, BOT_STATS, UCER_SETTINGS, track_user

def is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to access admin panel.")
        return
    await update.message.reply_text("<b>Admin Panel</b>", parse_mode=ParseMode.HTML, reply_markup=admin_panel_kb(BOT_CONFIG["GDFLIX_GLOBAL"]))

async def admin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        try: await q.message.delete()
        except Exception: pass
        return
    action = q.data.split(":")[1]
    if action == "close":
        await q.message.delete(); return
    if action == "gdflix":
        BOT_CONFIG["GDFLIX_GLOBAL"] = not BOT_CONFIG["GDFLIX_GLOBAL"]
        await q.message.edit_reply_markup(reply_markup=admin_panel_kb(BOT_CONFIG["GDFLIX_GLOBAL"]))
        return
    if action == "users":
        total = len(BOT_STATS["users"])
        await q.message.edit_text(f"<b>👥 BOT USERS</b>\n\nTotal users used bot: <b>{total}</b>", parse_mode=ParseMode.HTML, reply_markup=admin_panel_kb(BOT_CONFIG["GDFLIX_GLOBAL"]))
        return
    if action == "ucer":
        await q.message.edit_text(f"<b>🔑 UCER STATS</b>\n\nUsers with UCER entries: <b>{len(UCER_SETTINGS)}</b>", parse_mode=ParseMode.HTML, reply_markup=admin_panel_kb(BOT_CONFIG["GDFLIX_GLOBAL"]))
        return