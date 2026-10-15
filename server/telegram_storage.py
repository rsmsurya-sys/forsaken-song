"""
Legacy backward compatibility wrapper for telegram_storage.
All storage operations are now managed by server.cloud_storage.
"""
from server.cloud_storage import (
    LEGACY_TG_CONFIG_FILE as CONFIG_FILE,
    get_telegram_config,
    save_telegram_config,
    test_telegram_connection,
    upload_audio_to_telegram,
    get_telegram_file_stream_url,
    get_storage_config,
    save_storage_config,
    upload_audio_file,
    get_stream_url_for_song,
)

__all__ = [
    "CONFIG_FILE",
    "get_telegram_config",
    "save_telegram_config",
    "test_telegram_connection",
    "upload_audio_to_telegram",
    "get_telegram_file_stream_url",
    "get_storage_config",
    "save_storage_config",
    "upload_audio_file",
    "get_stream_url_for_song",
]
