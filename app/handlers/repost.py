import os
import re
import html
from io import BytesIO
from typing import Optional, Tuple

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# If your project already has a MediaInfo helper, import it here.
# Adjust these imports/names to match your existing codebase.
try:
    from app.services.mediainfo import probe_url as mediainfo_probe
except Exception:
    mediainfo_probe = None  # Fallback if not available


def _audio_enabled(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    UCER settings + global toggle:
    - If UCER toggled ON in your UI, set context.bot_data['ucer_audio_enabled'] = True.
    - DISABLE_MEDIAINFO=1 will force OFF.
    """
    if str(os.environ.get("DISABLE_MEDIAINFO", "0")).strip() == "1":
        return False
    return bool(context.bot_data.get("ucer_audio_enabled", True))


def _extract_first_url(text: str | None) -> Optional[str]:
    if not text:
        return None
    # Try anchor href (Click Here)
    m = re.search(r"""<a\s+href=['"]([^'"]+)['"]""", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Plain URL
    m = re.search(r"""https?://[^\s<>'"]+""", text)
    if m:
        return m.group(0).strip()
    return None


def _format_audio_block(info: dict | None) -> str:
    """
    Build a bold 'Audio' block in HTML.
    Expected info format:
      {
        "tracks": [
          {"lang": "English", "codec": "EAC3", "channels": "5.1", "bitrate": "640 kbps"},
          ...
        ]
      }
    Adjust this to match your mediainfo output.
    """
    if not info or not info.get("tracks"):
        return ""
    lines = ["\n<b>Audio:</b>"]
    for t in info["tracks"]:
        lang = t.get("lang") or t.get("language") or "Unknown"
        codec = t.get("codec") or t.get("format") or "Unknown"
        ch = t.get("channels") or t.get("ch") or "?"
        br = t.get("bitrate") or t.get("bit_rate") or ""
        sr = t.get("sample_rate") or ""
        parts = [lang, codec, f"{ch}ch"]
        if br:
            parts.append(str(br))
        if sr:
            parts.append(str(sr))
        lines.append("• " + " • ".join(html.escape(str(x)) for x in parts if x))
    return "\n".join(lines)


async def rk_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /rk — Repost the replied poster/photo/video with the same bold caption and buttons.
    If UCER settings are ON (and MediaInfo enabled), append Audio info block based on the URL in the caption.
    Usage:
      - Reply to a message that has the poster and caption, then send /rk.
      - The original message must contain a URL (e.g., 'Click Here') that points to the media file or source.
    """
    msg = update.message
    if not msg:
        return

    src = msg.reply_to_message
    if not src:
        await msg.reply_text("Reply to a message with a poster/photo/video and then use /rk.")
        return

    # Prefer HTML variants if available
    base_caption = (
        getattr(src, "caption_html", None)
        or getattr(src, "caption", None)
        or getattr(src, "text_html", None)
        or getattr(src, "text", None)
        or ""
    )

    reply_markup = src.reply_markup

    # Append audio info when enabled and a URL is available
    caption = base_caption or ""
    if _audio_enabled(context):
        url = _extract_first_url(caption)
        if not url and src and src.text:
            url = _extract_first_url(src.text)
        audio_block = ""
        if url and mediainfo_probe:
            try:
                info = mediainfo_probe(url)  # Adjust to your actual function signature
                audio_block = _format_audio_block(info)
            except Exception:
                audio_block = ""
        if audio_block:
            caption = f"{caption}\n{audio_block}"

    # Repost media with updated caption
    try:
        if src.photo:
            file_id = src.photo[-1].file_id
            await msg.chat.send_photo(photo=file_id, caption=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            return

        if src.animation:
            file_id = src.animation.file_id
            await msg.chat.send_animation(animation=file_id, caption=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            return

        if src.video:
            file_id = src.video.file_id
            await msg.chat.send_video(video=file_id, caption=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            return

        if src.document and (src.document.mime_type or "").startswith("image/"):
            file_id = src.document.file_id
            await msg.chat.send_photo(photo=file_id, caption=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            return

        # Fallback: just resend the caption
        if caption:
            await msg.chat.send_message(text=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            return

        await msg.reply_text("Couldn’t detect media or caption in the replied message.")
    except Exception as e:
        await msg.reply_text(f"❌ Repost failed:\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)
