import os
import io
import json
import logging
import hashlib
import hmac
import datetime
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, Any
import requests

logger = logging.getLogger(__name__)

# Settings file to persist credentials and provider settings
DATA_DIR = Path(os.getenv("MUSIC_DATA_DIR", "music_library"))
STORAGE_CONFIG_FILE = DATA_DIR / "storage_config.json"
LEGACY_TG_CONFIG_FILE = DATA_DIR / "telegram_config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "provider": "github",  # "github", "aws", "local"
    "github": {
        "token": "",
        "repo": "rsmsurya-sys/forsaken-song",
        "tag": "music-vault"
    },
    "aws": {
        "access_key_id": "",
        "secret_access_key": "",
        "bucket_name": "",
        "region": "ap-south-1",
        "endpoint_url": "",
        "public_url_prefix": ""
    },
    "catbox": {
        "userhash": ""
    },
    "telegram": {
        "bot_token": "",
        "chat_id": ""
    }
}

def get_storage_config() -> Dict[str, Any]:
    """
    Loads unified storage configuration from file or environment variables.
    Defaults to GitHub Cloud Storage.
    """
    config = dict(DEFAULT_CONFIG)
    config["github"] = dict(DEFAULT_CONFIG["github"])
    config["aws"] = dict(DEFAULT_CONFIG["aws"])
    config["catbox"] = dict(DEFAULT_CONFIG.get("catbox", {}))
    config["telegram"] = dict(DEFAULT_CONFIG.get("telegram", {}))

    # Load from storage_config.json if present
    if STORAGE_CONFIG_FILE.exists():
        try:
            data = json.loads(STORAGE_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                config["provider"] = data.get("provider", config["provider"])
                if "github" in data and isinstance(data["github"], dict):
                    config["github"].update(data["github"])
                if "aws" in data and isinstance(data["aws"], dict):
                    config["aws"].update(data["aws"])
                # Compatibility if previously stored as s3
                if "s3" in data and isinstance(data["s3"], dict):
                    config["aws"].update(data["s3"])
                if "catbox" in data and isinstance(data["catbox"], dict):
                    config["catbox"].update(data["catbox"])
                if "telegram" in data and isinstance(data["telegram"], dict):
                    config["telegram"].update(data["telegram"])
        except Exception as e:
            logger.warning("Error reading storage_config.json: %s", e)

    # Environment variables overrides
    env_provider = os.getenv("STORAGE_PROVIDER")
    if env_provider:
        config["provider"] = env_provider.lower()

    # GitHub Env
    if os.getenv("GITHUB_TOKEN"):
        config["github"]["token"] = os.getenv("GITHUB_TOKEN", "")
    if os.getenv("GITHUB_REPO"):
        config["github"]["repo"] = os.getenv("GITHUB_REPO", "")
    if os.getenv("GITHUB_TAG"):
        config["github"]["tag"] = os.getenv("GITHUB_TAG", "")

    # AWS Env
    if os.getenv("AWS_ACCESS_KEY_ID"):
        config["aws"]["access_key_id"] = os.getenv("AWS_ACCESS_KEY_ID", "")
    if os.getenv("AWS_SECRET_ACCESS_KEY"):
        config["aws"]["secret_access_key"] = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    if os.getenv("AWS_S3_BUCKET") or os.getenv("AWS_BUCKET_NAME"):
        config["aws"]["bucket_name"] = os.getenv("AWS_S3_BUCKET") or os.getenv("AWS_BUCKET_NAME", "")
    if os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"):
        config["aws"]["region"] = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "ap-south-1")
    if os.getenv("AWS_ENDPOINT_URL") or os.getenv("S3_ENDPOINT_URL"):
        config["aws"]["endpoint_url"] = os.getenv("AWS_ENDPOINT_URL") or os.getenv("S3_ENDPOINT_URL", "")
    if os.getenv("AWS_PUBLIC_URL_PREFIX") or os.getenv("CLOUDFRONT_URL"):
        config["aws"]["public_url_prefix"] = os.getenv("AWS_PUBLIC_URL_PREFIX") or os.getenv("CLOUDFRONT_URL", "")

    return config

def save_storage_config(config_data: Dict[str, Any]):
    """
    Saves unified storage configuration to disk.
    """
    STORAGE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    current = get_storage_config()

    if "provider" in config_data:
        current["provider"] = config_data["provider"].strip().lower()
    if "github" in config_data and isinstance(config_data["github"], dict):
        current["github"].update(config_data["github"])
    if "aws" in config_data and isinstance(config_data["aws"], dict):
        current["aws"].update(config_data["aws"])
    if "s3" in config_data and isinstance(config_data["s3"], dict):
        current["aws"].update(config_data["s3"])
    if "catbox" in config_data and isinstance(config_data["catbox"], dict):
        current["catbox"].update(config_data["catbox"])
    if "telegram" in config_data and isinstance(config_data["telegram"], dict):
        current["telegram"].update(config_data["telegram"])

    STORAGE_CONFIG_FILE.write_text(json.dumps(current, indent=2), encoding="utf-8")

# ==============================================================================
# 1. GitHub Releases Cloud Storage (100% Free / Unlimited Storage / 2GB per song)
# ==============================================================================

def upload_audio_to_github(file_path: Path, gh_cfg: Dict[str, str]) -> Optional[str]:
    """
    Uploads an audio file as an asset to a GitHub Release.
    Returns: Direct permanent download URL with global CDN & range streaming support.
    """
    token = gh_cfg.get("token", "").strip()
    repo = gh_cfg.get("repo", "").strip()
    tag = gh_cfg.get("tag", "music-vault").strip() or "music-vault"

    if not token or not repo:
        logger.warning("Incomplete GitHub credentials.")
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "Forsaken-Music-OS"
    }

    try:
        # 1. Check if release exists
        release_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
        r_res = requests.get(release_url, headers=headers, timeout=15)
        release_data = None

        if r_res.status_code == 200:
            release_data = r_res.json()
        elif r_res.status_code == 404:
            # Create release if it doesn't exist
            create_url = f"https://api.github.com/repos/{repo}/releases"
            create_payload = {
                "tag_name": tag,
                "name": "Forsaken Music Vault",
                "body": "Automated music cloud storage vault for FORSAKEN SONG.",
                "draft": False,
                "prerelease": False
            }
            c_res = requests.post(create_url, headers=headers, json=create_payload, timeout=20)
            if c_res.status_code in (200, 201):
                release_data = c_res.json()
            else:
                logger.error("Failed to create GitHub release: %s", c_res.text)
                return None
        else:
            logger.error("Failed to fetch GitHub release: %s", r_res.text)
            return None

        release_id = release_data.get("id")
        if not release_id:
            return None

        # Check if asset with this name already exists in release
        for asset in release_data.get("assets", []):
            if asset.get("name") == file_path.name:
                logger.info("Asset %s already exists in GitHub release, returning URL", file_path.name)
                return asset.get("browser_download_url")

        # 2. Upload asset
        safe_asset_name = urllib.parse.quote(file_path.name)
        upload_endpoint = f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?name={safe_asset_name}"

        ext = file_path.suffix.lower()
        content_types = {
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".flac": "audio/flac",
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".opus": "audio/opus",
            ".aac": "audio/aac",
        }
        content_type = content_types.get(ext, "audio/mpeg")

        with open(file_path, "rb") as f:
            upload_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type,
                "User-Agent": "Forsaken-Music-OS"
            }
            u_res = requests.post(upload_endpoint, headers=upload_headers, data=f, timeout=300)

        if u_res.status_code in (200, 201):
            asset_info = u_res.json()
            download_url = asset_info.get("browser_download_url")
            logger.info("Successfully uploaded %s to GitHub: %s", file_path.name, download_url)
            return download_url
        elif u_res.status_code == 422:
            # Asset already exists, re-fetch to get its browser_download_url
            r2 = requests.get(release_url, headers=headers, timeout=15)
            if r2.status_code == 200:
                for a in r2.json().get("assets", []):
                    if a.get("name") == file_path.name:
                        return a.get("browser_download_url")
        else:
            logger.error("GitHub asset upload failed (status %s): %s", u_res.status_code, u_res.text)

    except Exception as e:
        logger.error("Exception uploading audio to GitHub: %s", e)

    return None

def test_github_connection(gh_cfg: Dict[str, str]) -> Dict[str, Any]:
    """
    Tests GitHub repository access with Personal Access Token.
    """
    token = gh_cfg.get("token", "").strip()
    repo = gh_cfg.get("repo", "").strip()

    if not token:
        return {"ok": False, "error": "GitHub Personal Access Token (PAT) காலியாக உள்ளது. github.com/settings/tokens மூலம் Token உருவாக்கவும்."}
    if not repo or "/" not in repo:
        return {"ok": False, "error": "Repository பெயர் சரியாக உள்ளிடவும் (எ.கா. username/repo-name)."}

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "Forsaken-Music-OS"
    }

    try:
        res = requests.get(f"https://api.github.com/repos/{repo}", headers=headers, timeout=12)
        if res.status_code == 200:
            repo_info = res.json()
            full_name = repo_info.get("full_name", repo)
            is_private = repo_info.get("private", False)
            return {
                "ok": True,
                "provider": "github",
                "message": f"GitHub Repo '{full_name}' ({'Private' if is_private else 'Public'}) வெற்றிகரமாக இணைக்கப்பட்டது! (100% Free Unlimited Audio Storage, 2GB/song)"
            }
        elif res.status_code == 401:
            return {"ok": False, "error": "Invalid GitHub Token (401 Unauthorized). Token-ல் 'repo' scope உள்ளதா என பார்க்கவும்."}
        elif res.status_code == 404:
            return {"ok": False, "error": f"Repository '{repo}' கிடைக்கவில்லை அல்லது Private ஆக இருந்தால் Token-க்கு repo permission தேவை."}
        return {"ok": False, "error": f"GitHub API error (HTTP {res.status_code}): {res.text[:120]}"}
    except Exception as e:
        return {"ok": False, "error": f"GitHub சர்வரை தொடர்பு கொள்ள முடியவில்லை: {str(e)}"}

# ==============================================================================
# 2. AWS S3 Storage Implementation (Pure Python AWS SigV4)
# ==============================================================================

def _s3_sign_v4(method: str, uri: str, query: str, headers: Dict[str, str],
                 payload_sha256: str, access_key: str, secret_key: str,
                 region: str, service: str, amz_date: str) -> str:
    """Pure Python AWS SigV4 implementation for lightweight S3 uploads."""
    datestamp = amz_date[:8]
    canonical_uri = urllib.parse.quote(uri, safe="/~")
    canonical_querystring = query

    sorted_headers = sorted(headers.items(), key=lambda x: x[0].lower())
    canonical_headers = "".join([f"{k.lower()}:{v.strip()}\n" for k, v in sorted_headers])
    signed_headers = ";".join([k.lower() for k, _ in sorted_headers])

    canonical_request = f"{method}\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_sha256}"
    credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"

    def sign(key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_date = sign(("AWS4" + secret_key).encode("utf-8"), datestamp)
    k_region = sign(k_date, region)
    k_service = sign(k_region, service)
    k_signing = sign(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    return f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"

def upload_audio_to_aws(file_path: Path, aws_cfg: Dict[str, str]) -> Optional[str]:
    """
    Uploads audio file to AWS S3 bucket.
    Returns direct S3 or CloudFront URL.
    """
    access_key = aws_cfg.get("access_key_id", "").strip()
    secret_key = aws_cfg.get("secret_access_key", "").strip()
    bucket = aws_cfg.get("bucket_name", "").strip()
    region = aws_cfg.get("region", "ap-south-1").strip() or "ap-south-1"
    endpoint = aws_cfg.get("endpoint_url", "").rstrip("/")
    public_prefix = aws_cfg.get("public_url_prefix", "").rstrip("/")

    if not endpoint:
        endpoint = f"https://s3.{region}.amazonaws.com"

    if not bucket or not access_key or not secret_key:
        logger.warning("Incomplete AWS S3 credentials.")
        return None

    safe_name = urllib.parse.quote(file_path.name)
    key = f"songs/{safe_name}"
    uri = f"/{bucket}/{key}"

    parsed = urllib.parse.urlparse(endpoint)
    host = parsed.netloc

    ext = file_path.suffix.lower()
    content_types = {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".opus": "audio/opus",
        ".aac": "audio/aac",
    }
    content_type = content_types.get(ext, "audio/mpeg")

    try:
        payload = file_path.read_bytes()
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        now = datetime.datetime.now(datetime.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")

        headers = {
            "Host": host,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_sha256,
            "Content-Type": content_type,
            "Content-Length": str(len(payload))
        }

        auth = _s3_sign_v4("PUT", uri, "", headers, payload_sha256, access_key, secret_key, region, "s3", amz_date)
        headers["Authorization"] = auth

        put_url = f"{endpoint}{uri}"
        res = requests.put(put_url, headers=headers, data=payload, timeout=180)

        if res.status_code in (200, 201, 204):
            if public_prefix:
                return f"{public_prefix}/{key}"
            return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
        else:
            logger.error("AWS S3 upload failed (HTTP %s): %s", res.status_code, res.text)
    except Exception as e:
        logger.error("Exception uploading audio to AWS S3: %s", e)

    return None

def test_aws_connection(aws_cfg: Dict[str, str]) -> Dict[str, Any]:
    """
    Tests AWS S3 credentials and bucket accessibility.
    """
    bucket = aws_cfg.get("bucket_name", "").strip()
    access_key = aws_cfg.get("access_key_id", "").strip()
    secret_key = aws_cfg.get("secret_access_key", "").strip()
    region = aws_cfg.get("region", "ap-south-1").strip() or "ap-south-1"
    endpoint = aws_cfg.get("endpoint_url", "").rstrip("/")

    if not bucket:
        return {"ok": False, "error": "AWS S3 Bucket Name காலியாக உள்ளது."}
    if not access_key:
        return {"ok": False, "error": "AWS Access Key ID காலியாக உள்ளது."}
    if not secret_key:
        return {"ok": False, "error": "AWS Secret Access Key காலியாக உள்ளது."}

    if not endpoint:
        endpoint = f"https://s3.{region}.amazonaws.com"

    parsed = urllib.parse.urlparse(endpoint)
    host = parsed.netloc
    uri = f"/{bucket}/"

    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        empty_sha256 = hashlib.sha256(b"").hexdigest()

        headers = {
            "Host": host,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": empty_sha256
        }

        auth = _s3_sign_v4("HEAD", uri, "", headers, empty_sha256, access_key, secret_key, region, "s3", amz_date)
        headers["Authorization"] = auth

        res = requests.head(f"{endpoint}{uri}", headers=headers, timeout=12)
        if res.status_code in (200, 204, 301):
            return {
                "ok": True,
                "provider": "aws",
                "message": f"AWS S3 Bucket '{bucket}' ({region}) வெற்றிகரமாக இணைக்கப்பட்டது!"
            }
        elif res.status_code == 403:
            return {"ok": False, "error": "AWS S3 அணுகல் அனுமதி மறுக்கப்பட்டது (403 Forbidden). Access Key & Secret Key சரிபார்க்கவும்."}
        elif res.status_code == 404:
            return {"ok": False, "error": f"AWS S3 Bucket '{bucket}' கிடைக்கவில்லை (404 Not Found)."}
        return {"ok": False, "error": f"AWS S3 returned HTTP {res.status_code}"}
    except Exception as e:
        return {"ok": False, "error": f"AWS சர்வரை தொடர்பு கொள்ள முடியவில்லை: {str(e)}"}

# ==============================================================================
# 3. Fallbacks (Catbox, Local, Telegram)
# ==============================================================================

def upload_audio_to_catbox(file_path: Path, userhash: str = "") -> Optional[str]:
    url = "https://catbox.moe/user/api.php"
    data = {"reqtype": "fileupload"}
    if userhash and userhash.strip():
        data["userhash"] = userhash.strip()

    ext = file_path.suffix.lower()
    content_types = {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".opus": "audio/opus",
        ".aac": "audio/aac",
    }
    content_type = content_types.get(ext, "audio/mpeg")

    try:
        with open(file_path, "rb") as f:
            files = {"fileToUpload": (file_path.name, f, content_type)}
            res = requests.post(url, data=data, files=files, timeout=180)

        if res.status_code == 200:
            result_url = res.text.strip()
            if result_url.startswith("http://") or result_url.startswith("https://"):
                return result_url
    except Exception as e:
        logger.error("Exception uploading audio to Catbox: %s", e)
    return None

def upload_audio_to_telegram(file_path: Path, title: str, artist: str, duration: int = 0) -> Optional[str]:
    cfg = get_storage_config().get("telegram", {})
    token = cfg.get("bot_token", "").strip()
    chat_id = cfg.get("chat_id", "").strip()
    if not token or not chat_id:
        return None
    url = f"https://api.telegram.org/bot{token}/sendAudio"
    try:
        with open(file_path, "rb") as f:
            files = {"audio": (file_path.name, f, "audio/mpeg")}
            data = {"chat_id": chat_id, "title": title, "performer": artist, "duration": int(duration) if duration else 0}
            res = requests.post(url, files=files, data=data, timeout=120)
        if res.status_code == 200:
            result = res.json()
            if result.get("ok"):
                audio_obj = result["result"].get("audio") or result["result"].get("document")
                if audio_obj:
                    return audio_obj.get("file_id")
    except Exception as e:
        logger.error("Exception uploading audio to Telegram: %s", e)
    return None

def get_telegram_file_stream_url(file_id: str) -> Optional[str]:
    cfg = get_storage_config().get("telegram", {})
    token = cfg.get("bot_token", "").strip()
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

def test_telegram_connection(bot_token: str, chat_id: str) -> Dict[str, Any]:
    bot_token = bot_token.strip()
    chat_id = chat_id.strip()
    if not bot_token or not chat_id:
        return {"ok": False, "error": "Bot Token and Channel ID required"}
    try:
        me_res = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=12)
        me_data = me_res.json()
        if not me_data.get("ok"):
            return {"ok": False, "error": "Invalid Bot Token"}
        bot_user = me_data["result"].get("username", "Bot")
        return {"ok": True, "provider": "telegram", "message": f"Connected to @{bot_user}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ==============================================================================
# Unified Master Storage Orchestrator
# ==============================================================================

def upload_audio_file(file_path: Path, title: str, artist: str, duration: int = 0) -> Optional[Dict[str, Any]]:
    """
    Uploads audio file to the configured storage provider.
    Returns:
        dict: {"provider": "github"|"aws"|"local", "url": "...", "file_id": "..."}
    """
    cfg = get_storage_config()
    provider = cfg.get("provider", "github").lower()

    if provider == "github":
        gh_cfg = cfg.get("github", {})
        cloud_url = upload_audio_to_github(file_path, gh_cfg)
        if cloud_url:
            return {"provider": "github", "url": cloud_url, "file_id": None}

    elif provider in ("aws", "s3"):
        aws_cfg = cfg.get("aws", {})
        cloud_url = upload_audio_to_aws(file_path, aws_cfg)
        if cloud_url:
            return {"provider": "aws", "url": cloud_url, "file_id": None}

    elif provider == "catbox":
        userhash = cfg.get("catbox", {}).get("userhash", "")
        cloud_url = upload_audio_to_catbox(file_path, userhash)
        if cloud_url:
            return {"provider": "catbox", "url": cloud_url, "file_id": None}

    elif provider == "telegram":
        tg_file_id = upload_audio_to_telegram(file_path, title, artist, duration)
        if tg_file_id:
            return {"provider": "telegram", "url": None, "file_id": tg_file_id}

    elif provider == "local":
        return {"provider": "local", "url": None, "file_id": None}

    return None

def test_storage_connection(provider: str, config_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tests connection for any requested provider.
    """
    provider = provider.lower().strip()
    if provider == "github":
        return test_github_connection(config_data.get("github", {}))
    elif provider in ("aws", "s3"):
        return test_aws_connection(config_data.get("aws") or config_data.get("s3") or {})
    elif provider == "local":
        return {
            "ok": True,
            "provider": "local",
            "message": "Local PC Storage செயலில் உள்ளது. பாடல்கள் உங்கள் கணினியிலேயே (music_library/songs) சேமிக்கப்படும்."
        }
    elif provider == "catbox":
        userhash = config_data.get("catbox", {}).get("userhash", "")
        res = requests.get("https://catbox.moe", timeout=10)
        return {"ok": res.status_code < 500, "provider": "catbox", "message": "Catbox connected"}
    elif provider == "telegram":
        tg = config_data.get("telegram", {})
        return test_telegram_connection(tg.get("bot_token", ""), tg.get("chat_id", ""))
    return {"ok": False, "error": f"Unknown storage provider: {provider}"}

def get_stream_url_for_song(song: Dict[str, Any]) -> Optional[str]:
    """
    Returns direct streaming URL if the song is stored in Cloud.
    """
    if song.get("cloud_url"):
        return song["cloud_url"]
    if song.get("telegram_file_id"):
        return get_telegram_file_stream_url(song["telegram_file_id"])
    return None

# ==============================================================================
# Backward Compatibility Wrappers
# ==============================================================================

def get_telegram_config() -> Dict[str, str]:
    cfg = get_storage_config().get("telegram", {})
    return {"bot_token": cfg.get("bot_token", ""), "chat_id": cfg.get("chat_id", "")}

def save_telegram_config(bot_token: str, chat_id: str):
    save_storage_config({
        "provider": "telegram",
        "telegram": {"bot_token": bot_token.strip(), "chat_id": chat_id.strip()}
    })
