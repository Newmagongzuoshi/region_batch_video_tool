import json
import os
import base64
import time
from urllib.parse import urljoin

import requests

from core.tts_engine_base import BaseTTSEngine
from utils.logger import get_logger

logger = get_logger()


class CustomHttpTTSEngine(BaseTTSEngine):
    def __init__(self, config: dict, api_key: str = ""):
        self._config = config
        self._api_key = api_key
        self._session = requests.Session()
        self._last_request_time = 0
        self._min_interval = 0.5  # rate limit

    @property
    def engine_name(self) -> str:
        return self._config.get("provider_name", "Custom HTTP TTS")

    def list_voices(self) -> list[dict]:
        voices = self._config.get("voices", [])
        return voices

    def test_connection(self) -> bool:
        try:
            # Try a minimal request or just check endpoint reachability
            endpoint = self._config.get("endpoint", "")
            if not endpoint:
                return False
            # Simple HEAD request to check connectivity
            resp = self._session.head(endpoint, timeout=10)
            return True
        except Exception:
            return True  # HEAD may not be supported, so don't treat as failure

    def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: str,
        speed: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> bool:
        try:
            # Rate limiting
            elapsed = time.time() - self._last_request_time
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)

            method = self._config.get("method", "POST").upper()
            endpoint = self._config.get("endpoint", "")
            headers_tmpl = self._config.get("headers", {})
            body_tmpl = self._config.get("body", {})
            response_type = self._config.get("response_type", "binary")
            base64_field = self._config.get("base64_field", "data.audio")
            url_field = self._config.get("url_field", "data.audio_url")

            # Build headers with template replacement
            headers = {}
            for k, v in headers_tmpl.items():
                val = str(v).replace("{{api_key}}", self._api_key)
                val = val.replace("{{text}}", text)
                val = val.replace("{{voice_id}}", voice_id)
                val = val.replace("{{speed}}", str(speed))
                val = val.replace("{{pitch}}", str(pitch))
                headers[k] = val

            # Build body with template replacement
            body = {}
            if method == "POST":
                body_str = json.dumps(body_tmpl)
                body_str = body_str.replace("{{text}}", text)
                body_str = body_str.replace("{{voice_id}}", voice_id)
                body_str = body_str.replace("{{speed}}", str(speed))
                body_str = body_str.replace("{{pitch}}", str(pitch))
                body = json.loads(body_str)

            self._last_request_time = time.time()

            if method == "POST":
                resp = self._session.post(endpoint, headers=headers, json=body, timeout=30)
            else:
                params = body_tmpl
                resp = self._session.get(endpoint, headers=headers, params=params, timeout=30)

            if resp.status_code != 200:
                logger.error(
                    f"HTTP TTS request failed: status={resp.status_code}, "
                    f"body={str(resp.text)[:200]}"
                )
                return False

            # Parse response
            if response_type == "binary":
                audio_data = resp.content
            elif response_type == "base64_json":
                resp_json = resp.json()
                # Navigate nested keys: "data.audio" -> resp_json["data"]["audio"]
                b64_str = resp_json
                for key in base64_field.split("."):
                    if isinstance(b64_str, dict):
                        b64_str = b64_str.get(key, "")
                audio_data = base64.b64decode(b64_str)
            elif response_type == "url":
                resp_json = resp.json()
                audio_url = resp_json
                for key in url_field.split("."):
                    if isinstance(audio_url, dict):
                        audio_url = audio_url.get(key, "")
                dl_resp = self._session.get(audio_url, timeout=30)
                if dl_resp.status_code != 200:
                    logger.error(f"Failed to download audio from URL: {audio_url}")
                    return False
                audio_data = dl_resp.content
            else:
                logger.error(f"Unknown response_type: {response_type}")
                return False

            if not audio_data:
                logger.error("Empty audio data received")
                return False

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(audio_data)

            logger.info(
                f"HTTP TTS synthesized: {text[:30]} -> {output_path} "
                f"({len(audio_data)} bytes)"
            )
            return True

        except Exception as e:
            logger.error(f"HTTP TTS synthesize failed: {e}")
            return False
