import html
import logging
import re
import urllib.parse
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

def html_bold_lines(text: str) -> str:
    if not text:
        return ""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            out.append("")
        elif s.startswith("<b>") and s.endswith("</b>"):
            out.append(s)
        else:
            out.append(f"<b>{html.escape(s)}</b>")
    return "\n".join(out)

def ensure_line_bold(line: str) -> str:
    s = line.strip()
    if not s:
        return line
    if s.startswith("<b>") and s.endswith("</b>"):
        return line
    return f"<b>{s}</b>"

def is_gdrive_link(url: str) -> bool:
    return "drive.google.com" in url

def is_workers_link(url: str) -> bool:
    try:
        p = urllib.parse.urlparse(url)
        return "/0:" in (p.path or "")
    except Exception:
        return False

def extract_drive_id(url: str) -> Optional[str]:
    m = re.search(r"/file/d/([^/]+)", url)
    if m:
        return m.group(1)
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    if "id" in qs and qs["id"]:
        return qs["id"][0]
    return None

def extract_drive_id_from_workers(url: str) -> Optional[str]:
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    if "id" in qs and qs["id"]:
        return qs["id"][0]
    return None

def extract_workers_path(url: str) -> Optional[str]:
    try:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path or ""
        if "/0:" in path:
            return url
    except Exception:
        pass
    return None

def human_readable_size(size_bytes):
    try:
        size_bytes = int(size_bytes)
    except Exception:
        return "Unknown"
    if size_bytes <= 0:
        return "Unknown"
    gb = size_bytes / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.1f}GB"
    mb = size_bytes / (1024 ** 2)
    return f"{mb:.1f}MB"

def strip_extension(name: str) -> str:
    base = name.split("?")[0]
    m = re.match(r"^(.*)\.([A-Za-z0-9]{1,4})$", base)
    if m:
        return m.group(1)
    return base

def get_remote_size(url: str):
    try:
        r = requests.head(url, allow_redirects=True, timeout=20, verify=False)
        cl = r.headers.get("content-length") or r.headers.get("Content-Length")
        if cl:
            return int(cl)
    except Exception as e:
        logger.warning(f"HEAD size failed: {e}")
    return None

def download_bytes(url: str) -> Optional[bytes]:
    if not url:
        return None
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200 and r.content:
            return r.content
        logger.warning(f"Download HTTP {r.status_code} for {url}")
    except Exception as e:
        logger.warning(f"Download failed: {e}")
    return None