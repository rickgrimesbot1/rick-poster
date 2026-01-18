import json
import logging
import os
import threading
import time
from typing import Dict, Any, Set, List, Optional
from urllib.parse import urlparse

import requests
from app.config import STATE_REMOTE_URL as CFG_STATE_REMOTE_URL

logger = logging.getLogger(__name__)
STATE_FILE = "bot_state.json"
_state_lock = threading.Lock()

# Runtime state
BOT_STATS = {"users": set()}
BOT_CONFIG = {"GDFLIX_GLOBAL": True}
ALLOWED_USERS: List[int] = []
AUTHORIZED_CHATS: Set[int] = set()
UCER_SETTINGS: Dict[int, Dict[str, Any]] = {}

# Pending restart notify target (optional)
PENDING_RESTART: Optional[Dict[str, Any]] = None

# Remote state config
STATE_REMOTE_URL = (CFG_STATE_REMOTE_URL or os.getenv("STATE_REMOTE_URL", "")).strip()
STATE_REMOTE_TOKEN = os.getenv("STATE_REMOTE_TOKEN", "").strip()  # e.g., JSONBin X-Master-Key or your bearer token
STATE_REMOTE_TYPE = os.getenv("STATE_REMOTE_TYPE", "").strip().lower()  # "jsonbin" or ""
# Raw endpoint HTTP method override (POST or PUT). Default: POST.
STATE_REMOTE_METHOD = (os.getenv("STATE_REMOTE_METHOD", "POST") or "POST").strip().upper()

def _auto_infer_remote_type(url: str) -> str:
    if not url:
        return ""
    host = (urlparse(url).netloc or "").lower()
    if "jsonbin.io" in host:
        return "jsonbin"
    return STATE_REMOTE_TYPE or ""

def _jsonbin_headers(accept_only: bool = False) -> Dict[str, str]:
    h = {"Accept": "application/json"}
    if not accept_only:
        h["Content-Type"] = "application/json"
    if STATE_REMOTE_TOKEN:
        h["X-Master-Key"] = STATE_REMOTE_TOKEN
    return h

def _raw_headers(accept_only: bool = False) -> Dict[str, str]:
    h = {"Accept": "application/json"}
    if not accept_only:
        h["Content-Type"] = "application/json"
    if STATE_REMOTE_TOKEN:
        # support both Bearer and X-Token patterns
        h["Authorization"] = f"Bearer {STATE_REMOTE_TOKEN}"
        h["X-Token"] = STATE_REMOTE_TOKEN
    return h

def _apply_state_dict(data: dict):
    global UCER_SETTINGS, ALLOWED_USERS, AUTHORIZED_CHATS, PENDING_RESTART
    try:
        UCER_SETTINGS = {int(k): v for k, v in (data.get("ucer_settings") or {}).items()}
        for uid, cfg in UCER_SETTINGS.items():
            cfg.setdefault("gdflix", None)
            idxs = cfg.get("indexes")
            if not isinstance(idxs, list):
                cfg["indexes"] = []
                if isinstance(cfg.get("index"), str):
                    cfg["indexes"].append(cfg["index"])
            cfg["indexes"] = (cfg.get("indexes") or [])[:6]
            cfg.setdefault("full_name", False)
            cfg.setdefault("audio_format", False)

        ALLOWED_USERS = [int(x) for x in (data.get("allowed_users") or [])]
        AUTHORIZED_CHATS = set(int(x) for x in (data.get("authorized_chats") or []))

        pr = data.get("pending_restart")
        if isinstance(pr, dict) and pr.get("chat_id"):
            try:
                pr["chat_id"] = int(pr["chat_id"])
            except Exception:
                pass
            PENDING_RESTART = pr
        else:
            PENDING_RESTART = None

        logger.info(
            "State applied: users=%s groups=%s ucer=%s pending_restart=%s",
            len(ALLOWED_USERS), len(AUTHORIZED_CHATS), len(UCER_SETTINGS),
            'yes' if PENDING_RESTART else 'no'
        )
    except Exception as e:
        logger.warning(f"Failed to apply state: {e}")

def _jsonbin_get_url(url: str) -> str:
    url = url.rstrip("/")
    if not url.endswith("/latest"):
        url = url + "/latest"
    return url

def _jsonbin_put_url(url: str) -> str:
    # PUT goes to base bin URL (no /latest)
    return url.rstrip("/")

def _load_state_remote() -> bool:
    if not STATE_REMOTE_URL:
        logger.info("STATE_REMOTE_URL not set; skipping remote load.")
        return False
    rtype = _auto_infer_remote_type(STATE_REMOTE_URL)

    try:
        if rtype == "jsonbin":
            get_url = _jsonbin_get_url(STATE_REMOTE_URL)
            logger.info(f"Remote load (JSONBin GET): {get_url}")
            r = requests.get(get_url, headers=_jsonbin_headers(accept_only=True), timeout=12)
            logger.info(f"Remote GET status={r.status_code}")
            if r.status_code != 200:
                logger.warning(f"JSONBin GET failed: HTTP {r.status_code} {r.text[:200]}")
                return False
            js = r.json()
            # JSONBin shape: { record: {...}, metadata: {...} }
            if isinstance(js, dict) and isinstance(js.get("record"), dict):
                _apply_state_dict(js["record"])
                return True
            if isinstance(js, dict):
                _apply_state_dict(js)
                return True
            logger.warning("JSONBin response shape unexpected.")
            return False

        # RAW endpoint
        logger.info(f"Remote load (RAW GET): {STATE_REMOTE_URL}")
        r = requests.get(STATE_REMOTE_URL, headers=_raw_headers(accept_only=True), timeout=12)
        logger.info(f"Remote GET status={r.status_code}")
        if r.status_code != 200:
            logger.warning(f"Remote GET failed: HTTP {r.status_code} {r.text[:200]}")
            return False
        js = r.json()
        if not isinstance(js, dict):
            logger.warning("Remote state invalid JSON (expected dict).")
            return False
        _apply_state_dict(js)
        return True

    except Exception as e:
        logger.warning(f"Remote state GET error: {e}")
        return False

def _save_state_remote(data: dict) -> bool:
    if not STATE_REMOTE_URL:
        logger.info("STATE_REMOTE_URL not set; skipping remote save.")
        return False
    rtype = _auto_infer_remote_type(STATE_REMOTE_URL)

    try:
        if rtype == "jsonbin":
            put_url = _jsonbin_put_url(STATE_REMOTE_URL)
            logger.info(f"Remote save (JSONBin PUT): {put_url}")
            r = requests.put(put_url, headers=_jsonbin_headers(), data=json.dumps(data), timeout=15)
            logger.info(f"Remote PUT status={r.status_code}")
            if r.status_code not in (200, 201):
                logger.warning(f"JSONBin PUT failed: HTTP {r.status_code} {r.text[:200]}")
                return False
            return True

        # RAW endpoint
        method = STATE_REMOTE_METHOD if STATE_REMOTE_METHOD in ("POST", "PUT") else "POST"
        logger.info(f"Remote save (RAW {method}): {STATE_REMOTE_URL}")
        if method == "PUT":
            r = requests.put(STATE_REMOTE_URL, headers=_raw_headers(), data=json.dumps(data), timeout=12)
        else:
            r = requests.post(STATE_REMOTE_URL, headers=_raw_headers(), data=json.dumps(data), timeout=12)
        logger.info(f"Remote {method} status={r.status_code}")
        if r.status_code not in (200, 201, 204):
            logger.warning(f"Remote state {method} failed: HTTP {r.status_code} {r.text[:200]}")
            return False
        return True

    except Exception as e:
        logger.warning(f"Remote state {('PUT' if rtype=='jsonbin' else STATE_REMOTE_METHOD)} error: {e}")
        return False

def load_state():
    if _load_state_remote():
        return
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _apply_state_dict(data)
            logger.info("State loaded from local file.")
    except Exception as e:
        logger.warning(f"Failed to load local state: {e}")

def _current_state_dict() -> dict:
    return {
        "ucer_settings": UCER_SETTINGS,
        "allowed_users": ALLOWED_USERS,
        "authorized_chats": list(AUTHORIZED_CHATS),
        "pending_restart": PENDING_RESTART,
    }

def save_state():
    try:
        with _state_lock:
            data = _current_state_dict()
            # Save local
            try:
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.info("State saved locally.")
            except Exception as e:
                logger.warning(f"Failed to save local state: {e}")
            # Save remote
            _save_state_remote(data)
    except Exception as e:
        logger.warning(f"Failed to save state: {e}")

# Restart helpers
def mark_pending_restart(chat_id: int):
    global PENDING_RESTART
    PENDING_RESTART = {"chat_id": int(chat_id), "ts": int(time.time())}
    save_state()

def clear_pending_restart():
    global PENDING_RESTART
    PENDING_RESTART = None
    save_state()
