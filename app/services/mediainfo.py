import logging
import os
import re
import shutil
import subprocess
import tempfile
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
    # Try current PATH first
    path = shutil.which("mediainfo")
    if path:
        return path

    # Common Heroku apt buildpack locations
    candidates = [
        "/app/.apt/usr/bin/mediainfo",
        "/app/.apt/bin/mediainfo",
        "/usr/bin/mediainfo",
        "/usr/local/bin/mediainfo",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p

    # Try augmenting PATH (Heroku apt buildpack usually adds these already)
    extra = "/app/.apt/usr/bin:/app/.apt/bin"
    os.environ["PATH"] = f"{extra}:{os.environ.get('PATH', '')}"
    path = shutil.which("mediainfo")
    return path

def get_text_from_url_or_path(url: str) -> Optional[str]:
    temp_path = None
    target = url
    try:
        if url.startswith("http://") or url.startswith("https://"):
            r = requests.get(url, stream=True, timeout=60, verify=False)
            r.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
                temp_path = f.name
                downloaded = 0
                limit = 50 * 1024 * 1024
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded >= limit:
                        break
            target = temp_path

        bin_path = _resolve_mediainfo_bin()
        if not bin_path:
            logger.warning("mediainfo not found on PATH and known locations.")
            return None

        out = subprocess.check_output([bin_path, target], stderr=subprocess.STDOUT)
        return out.decode("utf-8", errors="ignore")
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
