from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from app.config import DEV_LINK

def access_denied_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("📩 Contact Admin", url=DEV_LINK)]])

def admin_panel_kb(gdflix_on: bool):
    status = "🟢 ON" if gdflix_on else "🔴 OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎞 GDFlix Mode: {status}", callback_data="admin:gdflix")],
        [InlineKeyboardButton("👥 Bot Users", callback_data="admin:users")],
        [InlineKeyboardButton("🔑 UCER Stats", callback_data="admin:ucer")],
        [InlineKeyboardButton("❌ Close", callback_data="admin:close")],
    ])

def ucer_main_kb(full_on: bool, audio_on: bool, idx_count: int):
    fullname_status = "🟢 ON" if full_on else "🔴 OFF"
    audio_status = "🟢 ON" if audio_on else "🔴 OFF"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔑 GdFlix API", callback_data="ucer:gdflix"),
            InlineKeyboardButton(f"📂 Index URLs ({idx_count}/6)", callback_data="ucer:indexes"),
        ],
        [
            InlineKeyboardButton(f"📄 Full File Name: {fullname_status}", callback_data="ucer:fullname"),
            InlineKeyboardButton(f"🔈 Audio Format: {audio_status}", callback_data="ucer:audiofmt"),
        ],
        [InlineKeyboardButton("❌ Close", callback_data="ucer:close")]
    ])

def ucer_sub_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add / Update", callback_data="ucer:add"),
         InlineKeyboardButton("⬅ Back", callback_data="ucer:back")],
        [InlineKeyboardButton("❌ Close", callback_data="ucer:close")]
    ])