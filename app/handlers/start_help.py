import html
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from app.config import DEV_LINK, START_PHOTO_URL, HELP_PHOTO_URL
from app.state import track_user

logger = logging.getLogger(__name__)

# ---------- Text builders (ALL BOLD) ----------
def _bold_lines(lines: list[str]) -> str:
    return "\n".join(f"<b>{l}</b>" if l.strip() else "" for l in lines)

def _basic_commands_text() -> str:
    return _bold_lines([
        "BASIC COMMANDS",
        "/start – Show welcome message",
        "/help – Show this help menu",
    ])

def _ott_commands_text() -> str:
    return _bold_lines([
        "OTT - COMMANDS",
        "• /amzn - Amazon Prime Video",
        "• /nf - Netflix",
        "• /snxt - SunNXT",
        "• /zee5 - Zee5",
        "• /aha - AhaVideo",
        "• /viki - Viki",
        "• /sl - SonyLiv",
        "• /hbo - HboMax",
        "• /up - UltraPlay",
        "• /iq - IQIYI",
        "• /hulu - Hulu",
        "• /apple - AppleTv",
        "• /dsnp - Disney+",
    ])

def _gd_commands_text() -> str:
    return _bold_lines([
        "GOOGLE DRIVE / DIRECT LINKS",
        "• /get – GDrive → GDFlix link + TMDB + MediaInfo",
        "• /rk - Post Replay to Any Ott link Send Get (Ott Poster with info)",
        "• /info – Direct link → TMDB + Audio Info",
        "• /ls – GDrive/Workers → GDFlix + TMDB + Audio Info",
        "• /tmdb – TMDB title/year/poster",
    ])

def _ucer_help_text() -> str:
    return _bold_lines([
        "Ucer",
        "• /start - Bot Dead Or Alive",
        "• /ucer - Ucer Settings",
        "• /amzn - Amazon Prime Video",
        "• /nf - Netflix",
        "• /snxt - SunNXT",
        "• /zee5 - Zee5",
        "• /aha - AhaVideo",
        "• /viki - Viki",
        "• /sl - SonyLiv",
        "• /hbo - HboMax",
        "• /up - UltraPlay",
        "• /iq - IQIYI",
        "• /hulu - Hulu",
        "• /apple - AppleTv",
        "• /dsnp - Disney+",
        "",
        "▣ Help Section!!",
        "◉ Check Button For Command",
        "◉ Need Assistance?",
        "~ If you are facing any problems, please ask the admin for help.",
    ])

def _admin_help_text() -> str:
    return _bold_lines([
        "ADMIN COMMANDS",
        "• /authorize – (Owner only) Authorize this group",
        "• /allow <user_id> – (Owner only) Allow a user",
        "• /deny <user_id> – (Owner only) Revoke a user",
    ])

def _main_help_caption(user_first_name: str) -> str:
    name = html.escape(user_first_name or "User")
    top = _bold_lines([
        "── ⋅ ⋅ ── ✩ ── ⋅ ⋅ ──╮",
        "╰┈➤  RICK BOT 🤖",
        "",
        f"Hello {name}!",
        "",
        "I am a Google Drive → GDFlix Poster & Audio Info Generator Bot",
        "",
        "➥ Developed By: @J1_CHANG_WOOK",
        "➥ Details: /help",
        "",
        "╰── ⋅ ⋅ ── ✩ ── ⋅ ⋅ ──╯",
        "",
    ])
    basic = _basic_commands_text()
    ott = _ott_commands_text()
    gd = _gd_commands_text()
    tail = _bold_lines([
        "━━━━━━━━━━━━━━━━━━",
        "➥ Developed By: J1_CHANG_WOOK",
        "",
        "▣ Help Section!!",
        "◉ Check Button For Command",
        "◉ Need Assistance?",
        "~ If you are facing any problems, please ask the admin for help.",
    ])
    # Compose with spacing between sections
    return "\n".join([top, basic, "", ott, "", gd, "", tail]).strip()

# ---------- Keyboards ----------
def _help_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📺 OTT Commands", callback_data="help:ott")],
        [InlineKeyboardButton("🗂 GD / Direct Commands", callback_data="help:gd")],
        [InlineKeyboardButton("🧩 UCER Help", callback_data="help:ucer")],
        [InlineKeyboardButton("🛡 Admin Help", callback_data="help:admin")],
    ]
    # Optional Developer button (URL)
    if DEV_LINK and DEV_LINK.startswith(("http://", "https://")):
        rows.append([InlineKeyboardButton("🤓 Bot Developer", url=DEV_LINK)])
    return InlineKeyboardMarkup(rows)

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)

    user = update.effective_user
    caption = _main_help_caption(user.first_name or "User")
    kb = _help_keyboard()

    if START_PHOTO_URL:
        try:
            await update.message.reply_photo(
                photo=START_PHOTO_URL,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
            return
        except Exception as e:
            logger.warning(f"/start photo failed: {e}")

    await update.message.reply_text(
        caption,
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        track_user(update.effective_user.id)

    caption = _bold_lines([
        "🤖 GDFlix TMDB Bot – HELP MENU",
        "",
        "Use the buttons below to view commands by category.",
    ])
    kb = _help_keyboard()

    if HELP_PHOTO_URL:
        try:
            await update.message.reply_photo(
                photo=HELP_PHOTO_URL,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
            return
        except Exception as e:
            logger.warning(f"/help photo failed: {e}")

    await update.message.reply_text(
        caption,
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )

async def help_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Callback for help menu buttons:
    - help:ott → send OTT commands (bold)
    - help:gd → send GD/Direct commands (bold)
    - help:ucer → send UCER text (bold)
    - help:admin → send Admin help (bold)
    """
    q = update.callback_query
    if not q:
        return
    try:
        await q.answer()
    except Exception:
        pass

    data = q.data or ""
    chat = q.message.chat if q.message else None
    if not chat:
        return

    if data == "help:ott":
        text = _ott_commands_text()
    elif data == "help:gd":
        text = _gd_commands_text()
    elif data == "help:ucer":
        text = _ucer_help_text()
    elif data == "help:admin":
        text = _admin_help_text()
    else:
        text = _bold_lines(["Unknown selection."])

    try:
        await chat.send_message(text=text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"help_cb send failed: {e}")
