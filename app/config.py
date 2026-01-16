import os

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")

# GDFlix
GDFLIX_API_KEY = os.getenv("GDFLIX_API_KEY", "")
GDFLIX_API_BASE = os.getenv("GDFLIX_API_BASE", "")
GDFLIX_FILE_BASE = os.getenv("GDFLIX_FILE_BASE", "")

# Workers
WORKERS_BASE = os.getenv("WORKERS_BASE", "")

# TMDB
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")

# UI / Developer links
DEV_LINK = os.getenv("DEV_LINK", "")
START_PHOTO_URL = os.getenv("START_PHOTO_URL", "")
HELP_PHOTO_URL = os.getenv("HELP_PHOTO_URL", "")

# Netflix poster worker
NETFLIX_API = os.getenv("NETFLIX_API", "")

# FreeImage hosting
FREEIMAGE_API_KEY = os.getenv("FREEIMAGE_API_KEY", "")
FREEIMAGE_UPLOAD_API = os.getenv("FREEIMAGE_UPLOAD_API", "")

# Remote state persistence
STATE_REMOTE_URL = os.getenv("STATE_REMOTE_URL", "").strip()
STATE_REMOTE_TOKEN = os.getenv("STATE_REMOTE_TOKEN", "").strip()  # e.g., JSONBin X-Master-Key
STATE_REMOTE_TYPE = os.getenv("STATE_REMOTE_TYPE", "").strip().lower()  # "jsonbin" or ""

# Optional local fallback state path
STATE_LOCAL_PATH = os.getenv("STATE_LOCAL_PATH", "bot_state.json")
