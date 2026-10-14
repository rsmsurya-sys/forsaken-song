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

def test_telegram_connection(bot_token: str, chat_id: str) -> Dict[str, Any]:
    bot_token = bot_token.strip()
    chat_id = chat_id.strip()

    if not bot_token:
        return {"ok": False, "error": "Bot Token empty-ஆ இருக்கு. @BotFather-லிருந்து கிடைத்த Token-ஐ Paste பண்ணுங்க."}
    if not chat_id:
        return {"ok": False, "error": "Chat/Channel ID empty-ஆ இருக்கு. Channel ID கொடுத்து சேமிக்கவும்."}

    # 1. Test Bot Token via getMe
    try:
        me_res = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=12)
        try:
            me_data = me_res.json()
        except Exception:
            return {"ok": False, "error": f"Telegram API response is not valid JSON (HTTP {me_res.status_code}). Please check internet or firewall."}
        if not me_data.get("ok"):
            return {"ok": False, "error": f"Invalid Bot Token: {me_data.get('description', 'Unauthorized')}. Bot Token சரியாக உள்ளதா என பார்க்கவும்."}
        bot_user = me_data["result"].get("username", "Bot")
    except Exception as e:
        return {"ok": False, "error": f"Telegram Server-ஐ தொடர்பு கொள்ள முடியவில்லை: {str(e)}"}

    # 2. Test Channel Access via getChat
    try:
        chat_res = requests.get(f"https://api.telegram.org/bot{bot_token}/getChat?chat_id={chat_id}", timeout=12)
        try:
            chat_data = chat_res.json()
        except Exception:
            return {"ok": False, "error": f"Telegram Channel response is not valid JSON (HTTP {chat_res.status_code})."}
        if not chat_data.get("ok"):
            desc = chat_data.get("description", "Chat not found")
            return {
                "ok": False, 
                "error": f"Channel Error ({desc}): உங்க Bot-ஐ (@{bot_user}) Channel-ல் Admin ஆக சேர்க்கவும் மற்றும் Chat ID சரியா (-100...) என பார்க்கவும்."
            }
        chat_title = chat_data["result"].get("title", chat_id)
    except Exception as e:
        return {"ok": False, "error": f"Channel சரிபார்க்க முடியவில்லை: {str(e)}"}

    return {
        "ok": True,
        "bot_username": bot_user,
        "chat_title": chat_title,
        "message": f"வெற்றிகரமாக இணைக்கப்பட்டது! Bot: @{bot_user} | Channel: {chat_title}"
    }

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
            try:
                result = res.json()
            except Exception:
                result = {}
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
            try:
                data = res.json()
            except Exception:
                data = {}
            if data.get("ok") and "file_path" in data.get("result", {}):
                file_path = data["result"]["file_path"]
                return f"https://api.telegram.org/file/bot{token}/{file_path}"
    except Exception as e:
        logger.error("Failed to get Telegram file url: %s", e)

    return None
