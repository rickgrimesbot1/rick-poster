import html
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from app.config import DEV_LINK, START_PHOTO_URL, HELP_PHOTO_URL
from app.state import track_user

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)
    user = update.effective_user
    name = html.escape(user.first_name or "User")
    text = (
        "<b>── ⋅ ⋅ ── ✩ ── ⋅ ⋅ ──╮</b>\n"
        "<b>╰┈➤  RICK BOT 🤖</b>\n\n"
        f"<b>Hello {name}!</b>\n\n"
        "<b>I am a Google Drive → GDFlix Poster & Audio Info Generator Bot</b>\n\n"
        "<b>➥ Developed By: @J1_CHANG_WOOK</b>\n"
        "<b>➥ Details: /help</b>\n\n"
        "<b>╰── ⋅ ⋅ ── ✩ ── ⋅ ⋅ ──╯</b>"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🤓 Bot Developer", url=DEV_LINK)]])
    if START_PHOTO_URL:
        try:
            await update.message.reply_photo(photo=START_PHOTO_URL, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
            return
        except Exception as e:
            logger.warning(f"/start photo failed: {e}")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)
    text = (
        "<b>🤖 GDFlix TMDB Bot – HELP MENU</b>\n\n"
        "<b>🟢 BASIC COMMANDS</b>\n"
        "<b>/start</b> – Show welcome message\n"
        "<b>/help</b> – Show this help menu\n"
        "<b>/authorize</b> – (Owner only) Authorize this group\n\n"
        "<b>🎬 GOOGLE DRIVE / DIRECT LINKS</b>\n"
        "<b>/get</b> – GDrive → GDFlix link + TMDB + MediaInfo\n"
        "<b>/info</b> – Direct link → TMDB + Audio Info\n"
        "<b>/ls</b> – GDrive/Workers → GDFlix + TMDB + Audio Info\n"
        "<b>/tmdb</b> – TMDB title/year/poster\n\n"
        "<b>📺 STREAMING POSTERS</b>\n"
        "<b>/amzn /airtel /zee5 /hulu /viki /mmax /snxt /aha /dsnp /apple /bms /iq /hbo /up /uj /wetv /sl /tk /nf</b>\n\n"
        "<b>🖼 MANUAL POSTER MODE</b>\n"
        "Use /get or /tmdb to generate caption → send/reply with a photo\n\n"
        "<b>━━━━━━━━━━━━━━━━━━</b>\n"
        "<b>➥ Developed By: <a href='https://t.me/J1_CHANG_WOOK'>J1_CHANG_WOOK</a></b>"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🤓 Bot Developer", url=DEV_LINK)]])
    if HELP_PHOTO_URL:
        try:
            await update.message.reply_photo(photo=HELP_PHOTO_URL, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
            return
        except Exception as e:
            logger.warning(f"/help photo failed: {e}")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)