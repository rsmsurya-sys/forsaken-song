import os
import io
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import requests

logger = logging.getLogger(__name__)

# Settings file to persist credentials entered via Admin page or env vars
CONFIG_FILE = Path(os.getenv("MUSIC_DATA_DIR", "music_library")) / "telegram_config.json"

def get_telegram_config() -> Dict[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            token = data.get("bot_token", token)
            chat_id = data.get("chat_id", chat_id)
        except Exception:
            pass
            
    return {"bot_token": token, "chat_id": chat_id}

def save_telegram_config(bot_token: str, chat_id: str):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({
        "bot_token": bot_token.strip(),
        "chat_id": chat_id.strip()
    }, indent=2), encoding="utf-8")

def upload_audio_to_telegram(file_path: Path, title: str, artist: str, duration: int = 0) -> Optional[str]:
    """
    Uploads an audio file to the configured Telegram channel/chat.
    Returns: file_id if successful, None otherwise.
    """
    config = get_telegram_config()
    token = config.get("bot_token")
    chat_id = config.get("chat_id")

    if not token or not chat_id:
        logger.warning("Telegram Bot Token or Chat ID not configured.")
        return None

    url = f"https://api.telegram.org/bot{token}/sendAudio"

    try:
        with open(file_path, "rb") as f:
            files = {"audio": (file_path.name, f, "audio/mpeg")}
            data = {
                "chat_id": chat_id,
                "title": title,
                "performer": artist,
                "duration": int(duration) if duration else 0,
            }
            res = requests.post(url, files=files, data=data, timeout=120)
            
        if res.status_code == 200:
            result = res.json()
            if result.get("ok"):
                audio_obj = result["result"].get("audio") or result["result"].get("document")
                if audio_obj:
                    return audio_obj.get("file_id")
        else:
            logger.error("Failed to upload audio to Telegram: %s", res.text)
    except Exception as e:
        logger.error("Exception uploading audio to Telegram: %s", e)

    return None

def get_telegram_file_stream_url(file_id: str) -> Optional[str]:
    """
    Retrieves direct download/streaming URL for a file stored on Telegram.
    """
    config = get_telegram_config()
    token = config.get("bot_token")
    if not token or not file_id:
        return None

    url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 200:
            data = res.json()
            if data.get("ok") and "file_path" in data.get("result", {}):
                file_path = data["result"]["file_path"]
                return f"https://api.telegram.org/file/bot{token}/{file_path}"
    except Exception as e:
        logger.error("Failed to get Telegram file url: %s", e)

    return None
