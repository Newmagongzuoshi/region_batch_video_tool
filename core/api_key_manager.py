import json
import os

from utils.crypto_utils import encrypt_value, decrypt_value, mask_api_key
from utils.path_utils import resolve_data_path, ensure_dir
from utils.logger import get_logger

logger = get_logger()

CONFIG_FILE = "api_keys.json"


class ApiKeyManager:
    def __init__(self):
        self._keys: dict[str, dict] = {}
        self._load()

    def _config_path(self) -> str:
        return resolve_data_path("config", CONFIG_FILE)

    def _load(self):
        path = self._config_path()
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._keys = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load API keys: {e}")
                self._keys = {}
        else:
            self._keys = {}

    def _save(self):
        path = self._config_path()
        ensure_dir(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._keys, f, ensure_ascii=False, indent=2)

    def add_key(self, config_id: str, api_key: str, display_name: str = "",
                secret_key: str = "", app_id: str = "", endpoint: str = "",
                provider: str = "custom_http") -> bool:
        encrypted_main = encrypt_value(api_key)
        encrypted_secret = encrypt_value(secret_key) if secret_key else ""

        self._keys[config_id] = {
            "display_name": display_name or config_id,
            "provider": provider,
            "api_key_encrypted": encrypted_main,
            "secret_key_encrypted": encrypted_secret,
            "app_id_encrypted": encrypt_value(app_id) if app_id else "",
            "endpoint": endpoint,
            "enabled": True,
        }
        self._save()
        logger.info(f"API key saved: {config_id} (display: {mask_api_key(api_key)})")
        return True

    def get_key(self, config_id: str) -> str:
        entry = self._keys.get(config_id)
        if not entry:
            return ""
        try:
            return decrypt_value(entry["api_key_encrypted"])
        except Exception as e:
            logger.error(f"Failed to decrypt API key {config_id}: {e}")
            return ""

    def get_secret_key(self, config_id: str) -> str:
        entry = self._keys.get(config_id)
        if not entry or not entry.get("secret_key_encrypted"):
            return ""
        try:
            return decrypt_value(entry["secret_key_encrypted"])
        except Exception:
            return ""

    def get_app_id(self, config_id: str) -> str:
        entry = self._keys.get(config_id)
        if not entry or not entry.get("app_id_encrypted"):
            return ""
        try:
            return decrypt_value(entry["app_id_encrypted"])
        except Exception:
            return ""

    def get_entry(self, config_id: str) -> dict | None:
        return self._keys.get(config_id)

    def get_masked_key(self, config_id: str) -> str:
        key = self.get_key(config_id)
        return mask_api_key(key) if key else ""

    def delete_key(self, config_id: str) -> bool:
        if config_id in self._keys:
            del self._keys[config_id]
            self._save()
            logger.info(f"API key deleted: {config_id}")
            return True
        return False

    def set_enabled(self, config_id: str, enabled: bool):
        if config_id in self._keys:
            self._keys[config_id]["enabled"] = enabled
            self._save()

    def list_configs(self) -> list[dict]:
        result = []
        for cid, entry in self._keys.items():
            result.append({
                "config_id": cid,
                "display_name": entry.get("display_name", cid),
                "provider": entry.get("provider", ""),
                "endpoint": entry.get("endpoint", ""),
                "enabled": entry.get("enabled", True),
                "masked_key": self.get_masked_key(cid),
            })
        return result
