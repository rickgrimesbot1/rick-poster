import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Tuple, Optional

import requests

logger = logging.getLogger(__name__)

def _extract_bitrate_from_string(s: str):
    if not s:
        return None
    m = re.findall(r'([0-9][0-9 .]*)(\s*(?:kb/s|kbps|Mb/s|mb/s|bits/s))', s, flags=re.IGNORECASE)
    if not m:
        return None
    num, unit = m[-1]
    num = num.replace(" ", "")
    unit = unit.lower().replace("kbps", "kb/s")
    return f"{num}{unit}"

def _map_codec_name(raw: str) -> str:
    if not raw:
        return ""
    r = raw.lower()
    if "atmos" in r:
        return "DDPA"
    if "dolby digital plus" in r or "e-ac-3" in r or "dd+" in r:
        return "DDP"
    if "ac-3" in r or "dolby digital" in r:
        return "DD"
    if "aac" in r:
        return "AAC"
    return raw.strip()

def _resolve_mediainfo_bin() -> Optional[str]:
    path = shutil.which("mediainfo")
    if path:
        return path
    for p in ("/app/.apt/usr/bin/mediainfo", "/app/.apt/bin/mediainfo", "/usr/bin/mediainfo", "/usr/local/bin/mediainfo"):
        if os.path.exists(p):
            return p
    extra = "/app/.apt/usr/bin:/app/.apt/bin"
    os.environ["PATH"] = f"{extra}:{os.environ.get('PATH', '')}"
    return shutil.which("mediainfo")

def _http_get_partial_to_file(url: str, limit_bytes: int = 50 * 1024 * 1024, timeout: int = 60) -> Optional[str]:
    """
    Download up to limit_bytes to a temp file with Range + retries and browser-like headers.
    Returns temp file path or None on failure.
    """
    headers_base = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
    }

    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            # Prefer Range request
            headers = dict(headers_base)
            headers["Range"] = f"bytes=0-{limit_bytes-1}"

            with requests.get(url, headers=headers, stream=True, timeout=timeout, verify=False) as r:
                status = r.status_code
                if status in (200, 206):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
                        downloaded = 0
                        for chunk in r.iter_content(chunk_size=1024 * 1024):
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            if downloaded >= limit_bytes:
                                break
                        return f.name
                elif 500 <= status < 600:
                    logger.warning(f"HTTP {status} from server (attempt {attempt}/3), retrying...")
                    time.sleep(1.5 * attempt)
                    continue
                else:
                    # Try fallback without Range once
                    if attempt == 1:
                        logger.warning(f"HTTP {status} on Range; retry without Range...")
                        with requests.get(url, headers=headers_base, stream=True, timeout=timeout, verify=False) as r2:
                            if r2.status_code == 200:
                                with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
                                    downloaded = 0
                                    for chunk in r2.iter_content(chunk_size=1024 * 1024):
                                        if not chunk:
                                            break
                                        f.write(chunk)
                                        downloaded += len(chunk)
                                        if downloaded >= limit_bytes:
                                            break
                                    return f.name
                            elif 500 <= r2.status_code < 600:
                                logger.warning(f"HTTP {r2.status_code} (no-Range) attempt {attempt}/3, retrying...")
                                time.sleep(1.5 * attempt)
                                continue
                            else:
                                logger.warning(f"HTTP {r2.status_code} (no-Range), giving up this attempt.")
                                time.sleep(0.5)
                                continue
        except requests.RequestException as e:
            logger.warning(f"Partial GET error (attempt {attempt}/3): {e}")
            time.sleep(1.0 * attempt)
        except Exception as e:
            logger.warning(f"Partial GET unexpected error (attempt {attempt}/3): {e}")
            time.sleep(1.0 * attempt)

    return None

def get_text_from_url_or_path(url: str) -> Optional[str]:
    temp_path = None
    target = url
    try:
        if url.startswith(("http://", "https://")):
            temp_path = _http_get_partial_to_file(url, limit_bytes=50 * 1024 * 1024, timeout=60)
            if not temp_path:
                logger.warning("mediainfo partial download failed (all retries).")
                return None
            target = temp_path

        bin_path = _resolve_mediainfo_bin()
        if not bin_path:
            logger.warning("mediainfo not found on PATH/known locations.")
            return None

        out = subprocess.check_output([bin_path, target], stderr=subprocess.STDOUT)
        return out.decode("utf-8", errors="ignore")

    except subprocess.CalledProcessError as e:
        logger.warning(f"mediainfo process error: {e.output.decode('utf-8', errors='ignore')[:400]}")
        return None
    except Exception as e:
        logger.warning(f"mediainfo failed: {e}")
        return None
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

def parse_audio_block(TEXT: str, ucer_format: bool) -> Tuple[str, Optional[str]]:
    if not TEXT:
        return "", None

    blocks = TEXT.split("\n\n")
    output = []
    raw_blocks = []
    for b in blocks:
        d = {}
        for line in b.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                d[k.strip()] = v.strip()
        if d:
            output.append(d)
            raw_blocks.append(b)

    org_aud = None
    audios = []
    idx = 1
    for i, d in enumerate(output):
        if "Channel(s)" in d:
            raw = raw_blocks[i]
            ch = d["Channel(s)"].replace(" channels", "")
            ch = "2.0" if ch == "2" else "5.1" if ch == "6" else "7.1" if ch == "8" else ch

            bitrate = ""
            for k, v in d.items():
                if "bit rate" in k.lower() or "bitrate" in k.lower():
                    cand = _extract_bitrate_from_string(v)
                    if cand:
                        bitrate = cand
                        break
            if not bitrate:
                cand = _extract_bitrate_from_string(raw)
                if cand:
                    bitrate = cand

            lang = d.get("Language", "")
            fmt = d.get("Commercial name") or d.get("Format") or ""
            codec = _map_codec_name(fmt)

            upper = codec.upper()
            if not bitrate:
                if "HE-AAC" in upper or "HE AAC" in upper:
                    bitrate = "96kb/s" if ch == "2.0" else "192kb/s" if ch == "5.1" else "256kb/s" if ch == "7.1" else ""
                elif "AAC" in upper:
                    bitrate = "128kb/s" if ch == "2.0" else "320kb/s" if ch == "5.1" else "448kb/s" if ch == "7.1" else ""
                elif "ATMOS" in upper:
                    bitrate = "768kb/s"
                elif "DDP" in upper or "E-AC-3" in upper or "DD+" in upper:
                    if ch == "5.1":
                        bitrate = "640kb/s"

            aud = {"ID": idx, "CHANNELS": ch, "BITRATE": bitrate, "LANGUAGE": lang, "CODEC": codec}
            audios.append(aud)
            idx += 1

    if not audios:
        return "", None

    if not ucer_format:
        lines = ["🎧 <b>Audio:</b>"]
        for a in audios:
            if a["ID"] == 1 and a["LANGUAGE"]:
                org_aud = a["LANGUAGE"]
            line = f"{a['ID']}. {a['LANGUAGE']} "
            if a.get("CODEC"):
                line += f"| {a['CODEC']} "
            if a.get("CHANNELS"):
                line += f"{a['CHANNELS']} "
            if a.get("BITRATE"):
                line += f"@ {a['BITRATE']}"
            lines.append(f"<b>{line.strip()}</b>")
        return "\n".join(lines), org_aud

    # UCER format
    rows = []
    for a in audios:
        if a["ID"] == 1 and a.get("LANGUAGE"):
            org_aud = a["LANGUAGE"]
        br = (a.get("BITRATE") or "").replace("kb/s", " kb/s").replace("Kb/s", " kb/s")
        parts = [p for p in [a.get("CODEC"), a.get("CHANNELS"), br, a.get("LANGUAGE")] if p]
        rows.append(" | ".join(parts))
    block = "🔈 <b>Audio Tracks:</b>\n<b><blockquote>" + "\n".join(rows) + "</blockquote></b>"
    return block, org_aud
