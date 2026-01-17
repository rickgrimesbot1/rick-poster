import html
import logging
import re
import urllib.parse
from typing import Optional, Tuple, Dict, Any, List

import aiohttp
from bs4 import BeautifulSoup
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.config import (
    GDFLIX_API_KEY, GDFLIX_API_BASE, GDFLIX_FILE_BASE,
    WORKERS_BASE, TMDB_API_KEY
)

logger = logging.getLogger(__name__)

TMDB_IMG_ORIGIN = "https://image.tmdb.org"
DIRECT_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif")

# ---------- Helpers already in your project ----------
try:
    from app.handlers.core import track_user
except Exception:
    def track_user(user_id: int):
        logger.debug(f"track_user noop for {user_id}")

# Optional UCER audio styling integration
try:
    from app.handlers.ucer import transform_audio_block as _transform_audio_block_to_ucer
except Exception:
    def _transform_audio_block_to_ucer(text: str, user_id: int) -> str:
        return text

# ---------- Session ----------
def _ensure_session(context: ContextTypes.DEFAULT_TYPE) -> aiohttp.ClientSession:
    session: Optional[aiohttp.ClientSession] = context.bot_data.get("_aiohttp_session")
    if session and not session.closed:
        return session
    timeout = aiohttp.ClientTimeout(total=16)
    connector = aiohttp.TCPConnector(limit=50, enable_cleanup_closed=True)
    session = aiohttp.ClientSession(timeout=timeout, connector=connector, headers={"User-Agent": "Mozilla/5.0"})
    context.bot_data["_aiohttp_session"] = session
    return session

# ---------- HTTP helpers ----------
async def _fetch_json(session: aiohttp.ClientSession, url: str, headers: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any] | List[Any]]:
    try:
        async with session.get(url, headers=headers) as r:
            if r.status != 200:
                logger.warning(f"_fetch_json {url} -> {r.status}")
                return None
            return await r.json(content_type=None)
    except Exception as e:
        logger.warning(f"_fetch_json failed for {url}: {e}")
        return None

async def _fetch_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    try:
        async with session.get(url) as r:
            if r.status != 200:
                return None
            return await r.text()
    except Exception as e:
        logger.warning(f"_fetch_text failed for {url}: {e}")
        return None

async def _download_bytes(session: aiohttp.ClientSession, url: str) -> Optional[bytes]:
    try:
        async with session.get(url) as r:
            if r.status != 200:
                return None
            return await r.read()
    except Exception as e:
        logger.warning(f"_download_bytes failed for {url}: {e}")
        return None

# ---------- URL helpers ----------
def _image_ext_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path or url
    ext = path.lower().rsplit(".", 1)
    return f".{ext[-1]}" if len(ext) > 1 else ""

def _is_direct_image_link(url: str) -> bool:
    return _image_ext_from_url(url) in DIRECT_IMAGE_EXTS

def _to_absolute_image_url(candidate: Optional[str], base: Optional[str] = None) -> Optional[str]:
    if not candidate:
        return candidate
    c = candidate.strip()
    if c.startswith("//"):
        return "https:" + c
    if c.startswith("/t/") or c.startswith("/p/") or c.startswith("/original") or re.match(r"^/w\d+/", c):
        return urllib.parse.urljoin(TMDB_IMG_ORIGIN, c)
    if c.startswith("/"):
        return urllib.parse.urljoin(base or TMDB_IMG_ORIGIN, c)
    return c

# ---------- Drive/OG helpers ----------
async def _resolve_og_image(session: aiohttp.ClientSession, page_url: str) -> Optional[str]:
    html_text = await _fetch_text(session, page_url)
    if not html_text:
        return None
    soup = BeautifulSoup(html_text, "html.parser")
    for key in ("og:image", "twitter:image", "og:image:url"):
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            return _to_absolute_image_url(tag["content"].strip(), base=page_url)
    return None

async def _resolve_og_title(session: aiohttp.ClientSession, page_url: str) -> Optional[str]:
    html_text = await _fetch_text(session, page_url)
    if not html_text:
        return None
    soup = BeautifulSoup(html_text, "html.parser")
    for key in ("og:title", "twitter:title"):
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            return tag["content"].strip()
    if soup.title and soup.title.text:
        return soup.title.text.strip()
    return None

def _sanitize_title_from_filename(name: str) -> Tuple[str, Optional[int], Optional[str]]:
    """
    Extract clean title and year from a noisy filename or page title.
    Also detect 'tv' vs 'movie' heuristically.
    """
    base = name
    base = re.sub(r"[._]+", " ", base)
    base = re.sub(r"\[[^\]]*\]", " ", base)
    base = re.sub(r"\([^\)]*\)", " ", base)
    common = r"(2160p|1080p|720p|480p|WEB[- ]?DL|WEBRip|BluRay|HDR|DV|HEVC|x265|x264|AV1|ATMOS|DDP|DD|AAC|EAC3|H264|H265|REMUX|CAM|TS|HC|Proper|Repack)"
    base = re.sub(rf"\b{common}\b", " ", base, flags=re.IGNORECASE)
    year = None
    m = re.search(r"\b(19|20)\d{2}\b", base)
    if m:
        try:
            year = int(m.group(0))
        except Exception:
            year = None
        base = base.replace(m.group(0), " ")
    tv = False
    if re.search(r"\bS\d{1,2}\b", base, flags=re.IGNORECASE) or re.search(r"\bSeason\b", base, flags=re.IGNORECASE):
        tv = True
    title = re.sub(r"\s+", " ", base).strip()
    return title, year, ("tv" if tv else None)

def _fallback_title_from_link(link: str) -> str:
    try:
        u = urllib.parse.urlparse(link)
        last = (u.path.rsplit("/", 1)[-1] or "").strip()
        if not last:
            last = u.netloc or "Untitled"
        clean, _, _ = _sanitize_title_from_filename(last)
        return clean or last or "Untitled"
    except Exception:
        return "Untitled"

# ---------- GDFlix resolve ----------
def _parse_query_id_from_gdflix_file(link: str) -> Optional[str]:
    try:
        u = urllib.parse.urlparse(link)
        if (GDFLIX_FILE_BASE and link.startswith(GDFLIX_FILE_BASE)) or "gdflix.dev" in (u.netloc or ""):
            qs = urllib.parse.parse_qs(u.query or "")
            for k in ("id", "file_id", "fid"):
                v = qs.get(k)
                if v and v[0]:
                    return v[0]
    except Exception:
        pass
    return None

async def _gdflix_resolve(session: aiohttp.ClientSession, link: str) -> Dict[str, Any]:
    """
    Try GDFlix API first, then worker fallback.
    Return dict with keys: title, year, tmdb_id, tmdb_type ('movie'/'tv'), audios (list), poster_url
    """
    out: Dict[str, Any] = {"title": "", "year": None, "tmdb_id": None, "tmdb_type": None, "audios": [], "poster_url": None}

    headers = {"User-Agent": "Mozilla/5.0"}
    if GDFLIX_API_KEY:
        headers["x-api-key"] = GDFLIX_API_KEY

    file_id = _parse_query_id_from_gdflix_file(link)
    if GDFLIX_API_BASE and file_id:
        for path in (f"/file?id={file_id}", f"/files/{file_id}", f"/v2/file?id={file_id}"):
            url = (GDFLIX_API_BASE.rstrip("/") + path)
            data = await _fetch_json(session, url, headers=headers)
            if not data:
                continue
            meta = data.get("meta") or data
            out["title"] = meta.get("title") or meta.get("name") or ""
            y = meta.get("year") or meta.get("release_year")
            if not y:
                rd = meta.get("release_date") or meta.get("date")
                if isinstance(rd, str) and len(rd) >= 4:
                    try:
                        y = int(rd[:4])
                    except Exception:
                        y = None
            out["year"] = y
            tmdb = meta.get("tmdb") or {}
            out["tmdb_id"] = tmdb.get("id") or meta.get("tmdb_id")
            out["tmdb_type"] = tmdb.get("type") or meta.get("type") or ("movie" if meta.get("is_movie") else "tv" if meta.get("is_tv") else None)
            p = meta.get("poster") or meta.get("poster_path") or tmdb.get("poster_path")
            out["poster_url"] = _to_absolute_image_url(p) if isinstance(p, str) else None
            auds = meta.get("audio") or meta.get("audios") or []
            if isinstance(auds, list):
                out["audios"] = auds
            break

    if (not out["tmdb_id"] or not out["tmdb_type"]) and WORKERS_BASE:
        try:
            wurl = f"{WORKERS_BASE.rstrip('/')}/?url={urllib.parse.quote_plus(link)}"
            data = await _fetch_json(session, wurl, headers=headers)
            if data:
                out["title"] = out["title"] or data.get("title") or data.get("name") or ""
                y = out["year"] or data.get("year") or data.get("release_year")
                if not y:
                    rd = data.get("release_date") or data.get("date")
                    if isinstance(rd, str) and len(rd) >= 4:
                        try:
                            y = int(rd[:4])
                        except Exception:
                            y = None
                out["year"] = y
                out["tmdb_id"] = out["tmdb_id"] or data.get("tmdb_id") or (data.get("tmdb") or {}).get("id")
                out["tmdb_type"] = out["tmdb_type"] or data.get("tmdb_type") or (data.get("tmdb") or {}).get("type")
                p = out["poster_url"] or data.get("poster") or data.get("poster_path")
                out["poster_url"] = _to_absolute_image_url(p) if isinstance(p, str) else out["poster_url"]
                auds = data.get("audio") or data.get("audios") or []
                if isinstance(auds, list) and not out["audios"]:
                    out["audios"] = auds
        except Exception as e:
            logger.warning(f"Worker resolve failed: {e}")

    return out

# ---------- TMDB search/details ----------
async def _tmdb_details(session: aiohttp.ClientSession, tmdb_id: Optional[int], tmdb_type: Optional[str]) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    if not tmdb_id or not tmdb_type or not TMDB_API_KEY:
        return None, None, None
    tmdb_type = tmdb_type.lower()
    if tmdb_type not in ("movie", "tv"):
        return None, None, None

    base = "https://api.themoviedb.org/3"
    url = f"{base}/{tmdb_type}/{tmdb_id}?api_key={TMDB_API_KEY}&language=en-US"
    data = await _fetch_json(session, url)
    if not data:
        return None, None, None

    if tmdb_type == "movie":
        title = data.get("title") or data.get("original_title")
        rd = data.get("release_date") or ""
    else:
        title = data.get("name") or data.get("original_name")
        rd = data.get("first_air_date") or ""

    year = None
    if isinstance(rd, str) and len(rd) >= 4:
        try:
            year = int(rd[:4])
        except Exception:
            year = None

    poster_path = data.get("poster_path") or data.get("backdrop_path")
    poster_url = _to_absolute_image_url(poster_path) if poster_path else None
    return title, year, poster_url

async def _tmdb_search_multi(session: aiohttp.ClientSession, query: str) -> Optional[Dict[str, Any]]:
    if not TMDB_API_KEY or not query:
        return None
    base = "https://api.themoviedb.org/3"
    url = f"{base}/search/multi?api_key={TMDB_API_KEY}&language=en-US&query={urllib.parse.quote_plus(query)}"
    data = await _fetch_json(session, url)
    if not data or not isinstance(data.get("results"), list) or not data["results"]:
        return None
    return data["results"][0]

async def _tmdb_search(session: aiohttp.ClientSession, query: str, year: Optional[int], prefer_type: Optional[str]) -> Tuple[Optional[int], Optional[str], Optional[str], Optional[int], Optional[str]]:
    """
    Search TMDB for a query; return (id, type, title, year, poster_url)
    """
    if not TMDB_API_KEY or not query:
        return None, None, None, None, None
    base = "https://api.themoviedb.org/3"
    types = ["movie", "tv"]
    if prefer_type in types:
        types = [prefer_type] + [t for t in types if t != prefer_type]

    # Try multi search first
    m = await _tmdb_search_multi(session, query)
    if m:
        mtype = m.get("media_type")
        if mtype in ("movie", "tv"):
            tid = m.get("id")
            title = m.get("title") or m.get("name")
            dstr = m.get("release_date") if mtype == "movie" else m.get("first_air_date")
            ryear = None
            if isinstance(dstr, str) and len(dstr) >= 4:
                try:
                    ryear = int(dstr[:4])
                except Exception:
                    ryear = None
            poster_path = m.get("poster_path") or m.get("backdrop_path")
            poster_url = _to_absolute_image_url(poster_path) if poster_path else None
            if tid:
                return tid, mtype, title, ryear, poster_url

    # Fallback: by type
    best = (None, None, None, None, None)
    for t in types:
        url = f"{base}/search/{t}?api_key={TMDB_API_KEY}&language=en-US&query={urllib.parse.quote_plus(query)}"
        if year and t == "movie":
            url += f"&year={year}"
        data = await _fetch_json(session, url)
        if not data or not isinstance(data.get("results"), list):
            continue
        for res in data["results"]:
            tid = res.get("id")
            if not tid:
                continue
            title = res.get("title") or res.get("name") or res.get("original_title") or res.get("original_name")
            dstr = res.get("release_date") if t == "movie" else res.get("first_air_date")
            ryear = None
            if isinstance(dstr, str) and len(dstr) >= 4:
                try:
                    ryear = int(dstr[:4])
                except Exception:
                    ryear = None
            poster_path = res.get("poster_path") or res.get("backdrop_path")
            poster_url = _to_absolute_image_url(poster_path) if poster_path else None

            qt = query.lower()
            tt = (title or "").lower()
            good = poster_url and (qt == tt or qt in tt or tt in qt)
            if good:
                return tid, t, title, ryear, poster_url

            if best[0] is None:
                best = (tid, t, title, ryear, poster_url)

        if best[0] is not None:
            break

    return best

# ---------- Caption (TOP) ----------
def _strip_b_tags(s: str) -> str:
    s = s.strip()
    if s.startswith("<b>") and s.endswith("</b>"):
        return s[3:-4].strip()
    return s

def _wrap_audio_block_in_blockquote(html_caption: str) -> str:
    """
    Make the Audio block like:
      <blockquote><b>🔈 Audio Tracks:</b>
        <b>DDP | 5.1 | 640 kb/s | Korean</b>
        <b>DDP | 5.1 | 640 kb/s | English</b></blockquote>
    """
    if not html_caption:
        return html_caption
    m = re.search(r'(?im)^\s*(?:<b>)?[^<]*audio\s*tracks\s*:\s*(?:</b>)?.*$', html_caption)
    if not m:
        return html_caption

    start_idx = m.start()
    tail = html_caption[start_idx:].strip()
    split_idx = tail.find("\n\n")
    if split_idx != -1:
        audio_block = tail[:split_idx]
        rest = tail[split_idx + 2 :]
    else:
        audio_block = tail
        rest = ""

    if audio_block.lstrip().startswith("<blockquote>"):
        return html_caption

    lines = [ln for ln in audio_block.splitlines() if ln.strip()]
    if not lines:
        return html_caption

    header_txt = _strip_b_tags(lines[0])
    header_line = f"<b>{header_txt}</b>"

    track_lines = []
    for ln in lines[1:]:
        t = _strip_b_tags(ln)
        if not t:
            continue
        track_lines.append(f"    <b>{t}</b>")

    quoted = "<blockquote>" + header_line
    if track_lines:
        quoted += "\n" + "\n".join(track_lines)
    quoted += "</blockquote>"

    prefix = html_caption[:start_idx]
    rebuilt = prefix + quoted
    if rest.strip():
        rebuilt += "\n\n" + rest
    return rebuilt

def _format_audio_tracks(audios: List[Dict[str, Any]]) -> str:
    if not audios:
        return ""
    lines = ["🔈 Audio Tracks:"]
    for a in audios:
        fmt = a.get("format") or a.get("codec") or a.get("name") or ""
        ch = a.get("channels") or a.get("channel") or a.get("layout") or ""
        br = a.get("bitrate") or a.get("kbps") or a.get("bit_rate") or ""
        lang = a.get("language") or a.get("lang") or a.get("locale") or ""
        parts = []
        if fmt: parts.append(str(fmt))
        if ch: parts.append(str(ch))
        if br: parts.append(f"{br} kb/s" if isinstance(br, (int, float)) else str(br))
        if lang: parts.append(str(lang))
        if parts:
            lines.append(" | ".join(parts))
    return "\n".join(lines)

def _build_top_caption(title: Optional[str], year: Optional[int], audios: List[Dict[str, Any]], user_id: int) -> str:
    top = []
    if title:
        if year:
            top.append(f"<b>{html.escape(title)} ({year})</b>")
        else:
            top.append(f"<b>{html.escape(title)}</b>")
    audio_text = _format_audio_tracks(audios)
    caption = "\n".join(top + ([audio_text] if audio_text else [])).strip()
    try:
        caption = _transform_audio_block_to_ucer(caption, user_id)
    except Exception:
        pass
    caption = _wrap_audio_block_in_blockquote(caption)
    return caption

def _ensure_non_empty_caption(caption: str, link: str, title: Optional[str], year: Optional[int]) -> str:
    """
    Avoid Telegram 'Message text is empty' by ensuring at least a bold title line.
    """
    if caption and caption.strip():
        return caption
    fallback_title = title or _fallback_title_from_link(link)
    if year:
        return f"<b>{html.escape(fallback_title)} ({year})</b>"
    return f"<b>{html.escape(fallback_title)}</b>"

def _reuse_replied_photo_file_id(update: Update) -> Optional[str]:
    """
    Reuse photo from replied message to place TOP caption like /get.
    """
    r = update.message.reply_to_message
    if not r:
        return None
    if r.photo and len(r.photo) > 0:
        return r.photo[-1].file_id
    return None

# ---------- Command ----------
async def flix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /flix <drive or GDFlix link>
    - Resolve GDFlix metadata (title, year, audio tracks)
    - Use TMDB to get poster and clean title/year
    - Send photo with TOP caption (like /get). If poster not found, reuse replied photo's file_id or send caption-only.
    """
    track_user(update.effective_user.id)
    msg = update.message
    if not msg:
        return

    # Accept link from args or replied text
    if context.args:
        link = context.args[0].strip()
    elif msg.reply_to_message and msg.reply_to_message.text:
        m = re.search(r"https?://\S+", msg.reply_to_message.text)
        link = m.group(0) if m else ""
    else:
        link = ""

    if not link:
        await msg.reply_text("❌ Usage:\n/flix <drive or GDFlix link>\nOr reply to a message containing the link and send /flix.", parse_mode=ParseMode.HTML)
        return

    session = _ensure_session(context)
    status = await msg.reply_text("🔎 Resolving GDFlix/TMDB...", parse_mode=ParseMode.HTML)

    try:
        meta = await _gdflix_resolve(session, link)

        # Prefer TMDB info
        tm_title, tm_year, tm_poster = await _tmdb_details(session, meta.get("tmdb_id"), meta.get("tmdb_type"))
        title = tm_title or meta.get("title") or ""
        year = tm_year or meta.get("year")
        poster_url = tm_poster or meta.get("poster_url")
        audios = meta.get("audios") or []

        # If missing, search TMDB by cleaned title (Drive page or filename)
        if (not title) or (not poster_url):
            og_title = await _resolve_og_title(session, link)
            candidate_title = og_title or title
            if not candidate_title:
                candidate_title = _fallback_title_from_link(link)
            clean_title, file_year, prefer_type = _sanitize_title_from_filename(candidate_title)
            search_year = year or file_year
            tid, ttype, stitle, syear, sposter = await _tmdb_search(session, clean_title, search_year, prefer_type)
            if tid and ttype:
                det_title, det_year, det_poster = await _tmdb_details(session, tid, ttype)
                title = det_title or stitle or title or clean_title
                year = det_year or syear or year or file_year
                poster_url = det_poster or sposter or poster_url
            else:
                # If TMDB search fails, at least set title from cleaned filename
                title = title or clean_title
                year = year or file_year

        # Final fallback: OG image from the page
        if not poster_url:
            poster_url = await _resolve_og_image(session, link)

        caption = _build_top_caption(title, year, audios, update.effective_user.id)
        caption = _ensure_non_empty_caption(caption, link, title, year)

        # If we have a poster URL, send photo with caption
        img_url = _to_absolute_image_url(poster_url) if poster_url else None
        if img_url and _is_direct_image_link(img_url):
            img_bytes = await _download_bytes(session, img_url)
            if img_bytes:
                from io import BytesIO
                bio = BytesIO(img_bytes); bio.name = "poster.jpg"
                try:
                    await status.delete()
                except Exception:
                    pass
                await msg.reply_photo(photo=bio, caption=caption, parse_mode=ParseMode.HTML)
                return

        # If poster fails, reuse replied photo (file_id) to keep TOP caption on image
        file_id = _reuse_replied_photo_file_id(update)
        try:
            await status.delete()
        except Exception:
            pass
        if file_id:
            await msg.reply_photo(photo=file_id, caption=caption, parse_mode=ParseMode.HTML)
        else:
            # As last resort, send caption-only (TOP text) like /get text mode — ensure non-empty
            await msg.reply_text(caption, parse_mode=ParseMode.HTML, disable_web_page_preview=False)

    except Exception as e:
        logger.exception("/flix failed")
        try:
            await status.edit_text(f"❌ Failed:\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)
        except Exception:
            await msg.reply_text(f"❌ Failed:\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)
