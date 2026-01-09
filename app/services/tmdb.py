import logging
import re
import requests
from typing import Optional, Tuple
from app.config import TMDB_API_KEY

logger = logging.getLogger(__name__)

LANG_MAP = {
    "en": "English", "ta": "Tamil", "te": "Telugu", "ml": "Malayalam",
    "hi": "Hindi", "kn": "Kannada", "mr": "Marathi", "bn": "Bengali",
    "pa": "Punjabi", "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
}

def pick_language(tmdb_lang_code: str | None, audio_lang: str | None) -> str:
    if audio_lang:
        return audio_lang
    code = (tmdb_lang_code or "").lower()
    if code in LANG_MAP:
        return LANG_MAP[code]
    if code:
        return code.upper()
    return "Unknown"

def extract_title_year_from_filename(filename: str) -> Tuple[str, str]:
    filename = filename.split("?")[0]
    name = filename.rsplit("/", 1)[-1]
    if "." in name:
        parts = name.split(".")
        if len(parts[-1]) <= 4:
            name = ".".join(parts[:-1]) or parts[0]
    clean = re.sub(r"[._]+", " ", name)
    clean = re.sub(r"-", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    m = re.search(r"(19|20)\d{2}", clean)
    if m:
        year = m.group(0)
        title_part = clean[:m.start()].strip()
    else:
        year = "????"
        title_part = clean.strip()
    title_part = re.sub(
        r"\b(480p|720p|1080p|2160p|4K|WEB[- ]DL|WEB[- ]Rip|WEBRip|NF|SS|AMZN|BluRay|Blu-Ray|HDRip|x264|x265|H\.264|H\.265|DDP|DD\+|DD|Atmos|AV1|HEVC|5\.1|7\.1)\b",
        "",
        title_part,
        flags=re.IGNORECASE,
    )
    title_part = re.sub(r"\s+", " ", title_part).strip()
    if not title_part:
        title_part = clean
    return title_part, year

def strict_match(raw_title: str, year: str):
    if not TMDB_API_KEY:
        logger.warning("TMDB_API_KEY not set")
        return None, None, None, None, None

    sxe = re.search(r"\bS(\d{1,2})E(\d{1,2})\b", raw_title, flags=re.IGNORECASE)
    if sxe:
        search_title = raw_title[:sxe.start()].strip()
    else:
        s_only = re.search(r"\bS(\d{1,2})\b", raw_title, flags=re.IGNORECASE)
        search_title = raw_title[:s_only.start()].strip() if s_only else raw_title.strip()
    if not search_title:
        search_title = raw_title.strip()
    have_year = year != "????"

    def search_movie():
        params = {"api_key": TMDB_API_KEY, "query": search_title, "include_adult": "false", "page": 1}
        if have_year: params["year"] = year
        try:
            r = requests.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=10)
            if r.status_code != 200: return []
            results = r.json().get("results") or []
            if not have_year: return results
            return [it for it in results if (it.get("release_date") or "")[:4] == year]
        except Exception:
            return []

    def search_tv():
        params = {"api_key": TMDB_API_KEY, "query": search_title, "include_adult": "false", "page": 1}
        if have_year: params["first_air_date_year"] = year
        try:
            r = requests.get("https://api.themoviedb.org/3/search/tv", params=params, timeout=10)
            if r.status_code != 200: return []
            results = r.json().get("results") or []
            if not have_year: return results
            return [it for it in results if (it.get("first_air_date") or "")[:4] == year]
        except Exception:
            return []

    item, ctype = None, None
    m_results = search_movie()
    if m_results:
        item, ctype = m_results[0], "movie"
    if not item:
        t_results = search_tv()
        if t_results:
            item, ctype = t_results[0], "tv"

    if not item and not have_year:
        try:
            r = requests.get("https://api.themoviedb.org/3/search/multi",
                             params={"api_key": TMDB_API_KEY, "query": search_title, "include_adult": "false", "page": 1},
                             timeout=10)
            if r.status_code == 200:
                res = r.json().get("results") or []
                if res:
                    item = res[0]
                    mt = item.get("media_type")
                    ctype = mt if mt in ("movie", "tv") else "movie"
        except Exception:
            pass

    if not item:
        return None, None, None, None, None

    tmdb_id = item.get("id")
    tmdb_title = item.get("title") or item.get("name") or search_title
    if item.get("release_date"):
        tmdb_year = item["release_date"][:4]
    elif item.get("first_air_date"):
        tmdb_year = item["first_air_date"][:4]
    else:
        tmdb_year = year
    lang_code = item.get("original_language", "")
    poster_path = item.get("poster_path")
    poster_url = f"https://image.tmdb.org/t/p/original{poster_path}" if poster_path else None

    if tmdb_id:
        if item.get("media_type") == "tv" or ctype == "tv":
            tmdb_url = f"https://www.themoviedb.org/tv/{tmdb_id}"
        else:
            tmdb_url = f"https://www.themoviedb.org/movie/{tmdb_id}"
    else:
        tmdb_url = None

    return tmdb_title, tmdb_year, lang_code, poster_url, tmdb_url

def backdrop_from_tmdb_url(tmdb_url: str | None) -> Optional[str]:
    if not tmdb_url or not TMDB_API_KEY:
        return None
    m = re.search(r"themoviedb\.org/(movie|tv)/(\d+)", tmdb_url)
    if not m: return None
    ctype, tmdb_id = m.group(1), m.group(2)
    try:
        api_url = f"https://api.themoviedb.org/3/{ctype}/{tmdb_id}/images"
        r = requests.get(api_url, params={"api_key": TMDB_API_KEY, "include_image_language": "en,null"}, timeout=10)
        if r.status_code != 200: return None
        backdrops = r.json().get("backdrops") or []
        if not backdrops: return None
        chosen = next((b for b in backdrops if b.get("iso_639_1") == "en"), None)
        if not chosen:
            chosen = next((b for b in backdrops if b.get("iso_639_1") in (None, "", "xx")), backdrops[0])
        fp = chosen.get("file_path")
        return f"https://image.tmdb.org/t/p/original{fp}" if fp else None
    except Exception:
        return None