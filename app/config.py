import os

try:
    from dotenv import load_dotenv, find_dotenv
   
    load_dotenv(find_dotenv(usecwd=True), override=False)
except Exception:
    ം
    pass

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")

# GDFlix
GDFLIX_API_KEY = os.getenv("GDFLIX_API_KEY", "").strip()
GDFLIX_API_BASE = os.getenv("GDFLIX_API_BASE", "https://gdflix.dev/v2").strip()
GDFLIX_FILE_BASE = os.getenv("GDFLIX_FILE_BASE", "https://gdflix.dev/file").strip()

# Workers
WORKERS_BASE = os.getenv("WORKERS_BASE", "").strip()

# TMDB
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()

# Start/help UI
DEV_LINK = os.getenv("DEV_LINK", "").strip()
START_PHOTO_URL = os.getenv("START_PHOTO_URL", "").strip()
HELP_PHOTO_URL = os.getenv("HELP_PHOTO_URL", "").strip()

# Netflix worker
NETFLIX_API = os.getenv("NETFLIX_API", "").strip()

# FreeImage host
FREEIMAGE_API_KEY = os.getenv("FREEIMAGE_API_KEY", "").strip()
FREEIMAGE_UPLOAD_API = os.getenv("FREEIMAGE_UPLOAD_API", "https://freeimage.host/api/1/upload").strip()

# Remote state
STATE_REMOTE_URL = os.getenv("STATE_REMOTE_URL", "").strip()
