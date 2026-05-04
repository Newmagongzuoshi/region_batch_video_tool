import os
import asyncio
import tempfile
import threading
import time
import uuid

from core.tts_engine_base import BaseTTSEngine
from utils.logger import get_logger

logger = get_logger()

EDGE_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓 (女声-温柔)"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊 (女声-活泼)"},
    {"id": "zh-CN-YunjianNeural", "name": "云健 (男声-运动)"},
    {"id": "zh-CN-YunxiNeural", "name": "云希 (男声-阳光)"},
    {"id": "zh-CN-YunxiaNeural", "name": "云夏 (男声-卡通)"},
    {"id": "zh-CN-YunyangNeural", "name": "云扬 (男声-新闻)"},
    {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "晓北 (东北话女声)"},
    {"id": "zh-CN-shaanxi-XiaoniNeural", "name": "晓妮 (陕西方言女声)"},
]


class EdgeTTSEngine(BaseTTSEngine):
    """Microsoft Edge TTS — free, no API key. Thread-safe with rate limiting."""

    MAX_RETRIES = 2

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self._ffmpeg = ffmpeg_path
        self._voice = "zh-CN-XiaoxiaoNeural"

    @property
    def engine_name(self) -> str:
        return "Edge TTS (免费)"

    def list_voices(self) -> list[dict]:
        return EDGE_VOICES

    def test_connection(self) -> bool:
        try:
            import edge_tts
            return True
        except ImportError:
            return False

    def _call_edge(self, text: str, voice: str, rate_str: str,
                   pitch_str: str, vol_str: str) -> bytes | None:
        """Call Edge TTS in a dedicated thread. Returns audio bytes or None."""
        import edge_tts

        communicate = edge_tts.Communicate(
            text=text, voice=voice,
            rate=rate_str, pitch=pitch_str, volume=vol_str,
        )

        tmp_mp3 = os.path.join(tempfile.gettempdir(),
                               f"_edge_{uuid.uuid4().hex[:8]}.mp3")
        err = []

        def _worker():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(communicate.save(tmp_mp3))
                loop.close()
            except Exception as e:
                err.append(e)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout=30)

        if err:
            logger.error(f"Edge TTS async error: {err[0]}")
            return None

        if os.path.isfile(tmp_mp3) and os.path.getsize(tmp_mp3) >= 100:
            with open(tmp_mp3, "rb") as f:
                data = f.read()
            try:
                os.remove(tmp_mp3)
            except Exception:
                pass
            return data

        try:
            os.remove(tmp_mp3)
        except Exception:
            pass
        return None

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
            return False

        try:
            voice = voice_id or self._voice
            rate_str = f"{int((speed - 1.0) * 100):+d}%"
            pitch_str = f"{int((pitch - 1.0) * 10):+d}Hz"
            vol_str = f"{int((volume - 1.0) * 100):+d}%"

            for attempt in range(self.MAX_RETRIES + 1):
                audio_data = self._call_edge(text, voice, rate_str, pitch_str, vol_str)
                if audio_data:
                    if output_path:
                        os.makedirs(os.path.dirname(output_path), exist_ok=True)
                        with open(output_path, "wb") as f:
                            f.write(audio_data)
                        logger.info(f"Edge TTS: '{text[:30]}' -> {output_path}")
                    return True
                if attempt < self.MAX_RETRIES:
                    delay = 2 ** (attempt + 2)  # 4s, 8s
                    logger.warning(f"Edge TTS retry {attempt+1}/{self.MAX_RETRIES} (wait {delay}s)...")
                    time.sleep(delay)

            logger.error(f"Edge TTS: all {self.MAX_RETRIES+1} attempts failed")
            return False

        except ImportError:
            logger.error("edge-tts not installed. pip install edge-tts")
            return False
        except Exception as e:
            logger.error(f"Edge TTS error: {e}")
            return False
