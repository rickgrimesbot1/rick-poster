import json
import logging
import os
import threading
from typing import Dict, Any, Set, List
import requests
from app.config import STATE_REMOTE_URL

logger = logging.getLogger(__name__)
STATE_FILE = "bot_state.json"
_state_lock = threading.Lock()

# Runtime state
BOT_STATS = {"users": set()}
BOT_CONFIG = {"GDFLIX_GLOBAL": True}
ALLOWED_USERS: List[int] = []
AUTHORIZED_CHATS: Set[int] = set()
UCER_SETTINGS: Dict[int, Dict[str, Any]] = {}

def track_user(user_id: int):
    try:
        BOT_STATS["users"].add(user_id)
    except Exception:
        pass

def _apply_state_dict(data: dict):
    global UCER_SETTINGS, ALLOWED_USERS, AUTHORIZED_CHATS
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
        logger.info(f"State applied: users={len(ALLOWED_USERS)} groups={len(AUTHORIZED_CHATS)} ucer={len(UCER_SETTINGS)}")
    except Exception as e:
        logger.warning(f"Failed to apply state: {e}")

def _load_state_remote() -> bool:
    if not STATE_REMOTE_URL:
        return False
    try:
        r = requests.get(STATE_REMOTE_URL, timeout=10)
        if r.status_code != 200:
            logger.warning(f"Remote state GET failed: HTTP {r.status_code}")
            return False
        js = r.json()
        if not isinstance(js, dict):
            logger.warning("Remote state invalid JSON")
            return False
        _apply_state_dict(js)
        logger.info("State loaded from remote.")
        return True
    except Exception as e:
        logger.warning(f"Remote state GET error: {e}")
        return False

def _save_state_remote(data: dict) -> bool:
    if not STATE_REMOTE_URL:
        return False
    try:
        r = requests.post(STATE_REMOTE_URL, json=data, timeout=10)
        if r.status_code not in (200, 201, 204):
            logger.warning(f"Remote state POST failed: HTTP {r.status_code} {r.text[:200]}")
            return False
        logger.info("State saved to remote.")
        return True
    except Exception as e:
        logger.warning(f"Remote state POST error: {e}")
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

def save_state():
    try:
        with _state_lock:
            data = {
                "ucer_settings": UCER_SETTINGS,
                "allowed_users": ALLOWED_USERS,
                "authorized_chats": list(AUTHORIZED_CHATS),
            }
            try:
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.info("State saved locally.")
            except Exception as e:
                logger.warning(f"Failed to save local state: {e}")
            _save_state_remote(data)
    except Exception as e:
        logger.warning(f"Failed to save state: {e}")