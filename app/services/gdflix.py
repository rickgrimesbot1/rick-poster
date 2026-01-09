import logging
import requests
from app.config import GDFLIX_API_BASE, GDFLIX_API_KEY, GDFLIX_FILE_BASE
logger = logging.getLogger(__name__)

def share_file(file_id: str, api_key: str | None = None):
    key = api_key or GDFLIX_API_KEY
    if not key or not GDFLIX_API_BASE:
        logger.warning("GDFLIX not configured")
        return None
    url = f"{GDFLIX_API_BASE}/share"
    try:
        r = requests.get(url, params={"key": key, "id": file_id}, timeout=30, verify=False)
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            logger.warning(f"GDFLIX error: {data.get('message')}")
            return None
        return data
    except Exception as e:
        logger.warning(f"GDFLIX HTTP error: {e}")
        return None

def file_link_from_response(res: dict, file_id: str) -> str:
    key = res.get("key")
    return f"{GDFLIX_FILE_BASE}/{key or file_id}"