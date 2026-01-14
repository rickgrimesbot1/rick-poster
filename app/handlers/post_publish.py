import re
import html
import logging
from typing import Optional, Union

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Storage keys in bot_data
CHANNEL_ID_KEY = "post_channel_id"

# Helpers -------------------------------------------------------------

def _normalize_channel_id(text: str) -> Optional[Union[str, int]]:
    """
    Accept:
    - @publicusername
    - https://t.me/publicusername  → @publicusername
    - -1001234567890 (as str or int)
    Return:
    - @username (str) OR int(-100...)
    """
    if not text:
        return None

    t = text.strip()

    # t.me url
    m = re.match(r"^https?://t\.me/([A-Za-z0-9_]+)$", t)
    if m:
        return f"@{m.group(1)}"

    # @username
    if t.startswith("@"):
        return t

    # numeric id
    try:
        n = int(t)
        # Channels are typically -100xxxxxxxxxx
        return n
    except ValueError:
        pass

    return None


async def _resolve_or_fail(update: Update, context: ContextTypes.DEFAULT_TYPE, arg_channel: Optional[str]) -> Optional[Union[str, int]]:
    """
    Pick channel from:
    - arg (if provided)
    - stored setting in bot_data
    Validate with get_chat; return normalized id or None (and reply with error).
    """
    candidate = None

    if arg_channel:
        candidate = _normalize_channel_id(arg_channel)
        if candidate is None:
            await update.message.reply_text("❌ Invalid channel. Use @username or -100... or https://t.me/username")
            return None
    else:
        stored = context.bot_data.get(CHANNEL_ID_KEY)
        if not stored:
            await update.message.reply_text("❌ No channel configured. Reply with /setchannel @username or -100.. to set one.")
            return None
        candidate = stored

    # Validate by get_chat (does not require admin)
    try:
        await context.bot.get_chat(candidate)
    except BadRequest as e:
        await update.message.reply_text(f"❌ Unable to access channel. Ensure the username/ID is correct.\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)
        return None
    except Forbidden as e:
        # Bot is blocked or not in channel
        await update.message.reply_text("❌ Bot is not a member of that channel. Add the bot as an Admin and try again.")
        return None
    except Exception as e:
        await update.message.reply_text(f"❌ Channel check failed:\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)
        return None

    return candidate


# Commands ------------------------------------------------------------

async def setchannel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /setchannel @username OR /setchannel -1001234567890
    Stores the target channel for /post.
    """
    msg = update.message
    if not context.args:
        await msg.reply_text("Usage:\n/setchannel @username\n/setchannel -1001234567890\n/setchannel https://t.me/username")
        return

    target_raw = context.args[0]
    target = await _resolve_or_fail(update, context, target_raw)
    if target is None:
        return

    context.bot_data[CHANNEL_ID_KEY] = target
    await msg.reply_text("✅ Channel saved for posting.\nTip: Reply to a poster and use /post to publish to the channel.")

async def clearchannel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /clearchannel — remove stored channel.
    """
    context.bot_data.pop(CHANNEL_ID_KEY, None)
    await update.message.reply_text("✅ Cleared stored channel.")

async def post_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /post [@username|-100id]
    - Must be used as a reply to the message you want to post
    - Copies the replied message (media + caption + buttons) to the configured channel
    - You can override channel by passing it as an argument
    """
    msg = update.message
    replied = msg.reply_to_message

    if not replied:
        await msg.reply_text("❌ Reply to the message you want to post, then send /post.\nOptionally: /post @channelusername")
        return

    # Optional override channel via arg
    arg_channel = context.args[0] if context.args else None
    target_channel = await _resolve_or_fail(update, context, arg_channel)
    if target_channel is None:
        return

    # Try copying the message to channel. This keeps media, caption, buttons.
    try:
        sent = await context.bot.copy_message(
            chat_id=target_channel,
            from_chat_id=msg.chat.id,
            message_id=replied.message_id,
            # If you want to silence notifications in the channel, add:
            # disable_notification=True,
        )
    except Forbidden as e:
        await msg.reply_text("❌ I don't have permission to post in that channel. Please add me as an Admin with 'Post Messages' permission.")
        return
    except BadRequest as e:
        await msg.reply_text(f"❌ Copy failed: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)
        return
    except Exception as e:
        await msg.reply_text(f"❌ Unexpected error: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)
        return

    # Success feedback
    stored = context.bot_data.get(CHANNEL_ID_KEY)
    where = arg_channel or (stored if stored else target_channel)
    await msg.reply_text(f"✅ Posted to {where}")
