import os
import json
import uuid
import time

import requests

from core.tts_engine_base import BaseTTSEngine
from utils.logger import get_logger

logger = get_logger()

# Volcengine TTS API endpoint
VOLC_TTS_URL = "https://openspeech.bytedance.com/api/v1/tts"

# Common voice types
VOICE_TYPES = [
    {"id": "BV001_streaming", "name": "通用女声-标准"},
    {"id": "BV002_streaming", "name": "通用男声-标准"},
    {"id": "BV003_streaming", "name": "情感女声"},
    {"id": "BV004_streaming", "name": "情感男声"},
    {"id": "BV005_streaming", "name": "知性女声"},
    {"id": "BV006_streaming", "name": "可爱女声"},
    {"id": "BV007_streaming", "name": "自然女声"},
    {"id": "BV008_streaming", "name": "温柔女声"},
    {"id": "BV009_streaming", "name": "活力女声"},
    {"id": "BV010_streaming", "name": "客服女声"},
    {"id": "BV011_streaming", "name": "成熟男声"},
    {"id": "BV012_streaming", "name": "磁性男声"},
    {"id": "BV013_streaming", "name": "新闻女声"},
    {"id": "BV014_streaming", "name": "新闻男声"},
    {"id": "BV015_streaming", "name": "活泼女声"},
    {"id": "ZH_CN_male", "name": "中文男声"},
    {"id": "ZH_CN_female", "name": "中文女声"},
]


class VolcengineTTSEngine(BaseTTSEngine):
    """Volcengine (火山引擎) TTS via HTTP API."""

    def __init__(self, app_id: str, access_token: str, voice_type: str = "BV001_streaming",
                 cluster: str = "volcano_tts"):
        self._app_id = app_id
        self._access_token = access_token
        self._voice_type = voice_type
        self._cluster = cluster
        self._session = requests.Session()

    @property
    def engine_name(self) -> str:
        return "火山引擎 TTS"

    def list_voices(self) -> list[dict]:
        return VOICE_TYPES

    def test_connection(self) -> bool:
        """Quick test: synthesize a single character and check response."""
        try:
            return self.synthesize("测试", self._voice_type, "")
        except Exception:
            return False

    def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: str,
        speed: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> bool:
        if not text:
            logger.error("Empty text for TTS")
            return False

        voice = voice_id or self._voice_type

        try:
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }
            body = {
                "app": {
                    "appid": self._app_id,
                    "token": self._access_token,
                    "cluster": self._cluster,
                },
                "user": {"uid": "region_batch_tool"},
                "audio": {
                    "voice_type": voice,
                    "encoding": "mp3",
                    "speed_ratio": round(speed, 1),
                },
                "request": {
                    "reqid": str(uuid.uuid4()),
                    "text": text,
                    "text_type": "plain",
                    "operation": "query",
                    "with_frontend": 1,
                    "frontend_type": "unitTson",
                },
            }

            resp = self._session.post(
                VOLC_TTS_URL, headers=headers, json=body, timeout=30
            )

            if resp.status_code != 200:
                logger.error(f"Volcengine TTS: HTTP {resp.status_code}: {resp.text[:300]}")
                return False

            data = resp.json()
            code = data.get("code", -1)
            if code != 3000:
                logger.error(f"Volcengine TTS: API error code={code}, msg={data.get('message', '')}")
                return False

            audio_b64 = data.get("data", "")
            if not audio_b64:
                logger.error("Volcengine TTS: empty audio data")
                return False

            import base64
            audio_data = base64.b64decode(audio_b64)

            if output_path:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(audio_data)
                logger.info(f"Volcengine TTS: '{text[:30]}' -> {output_path} ({len(audio_data)}B)")
            return True

        except Exception as e:
            logger.error(f"Volcengine TTS error: {e}")
            return False
