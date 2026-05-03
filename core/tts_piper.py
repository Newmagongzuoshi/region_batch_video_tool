import os
import io
import wave

from core.tts_engine_base import BaseTTSEngine
from utils.audio_utils import wav_to_mp3
from utils.logger import get_logger

logger = get_logger()

# Available Piper voices for download (Chinese + common)
PIPER_VOICES = [
    {"id": "zh_CN-huayan-medium", "name": "花颜 (中文女声)"},
    {"id": "en_US-lessac-medium", "name": "Lessac (英文女声)"},
    {"id": "en_US-ryan-high", "name": "Ryan (英文男声)"},
]

MODEL_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


class PiperTTSEngine(BaseTTSEngine):
    """Piper TTS — fully local neural TTS, no internet needed after model download."""

    def __init__(self, ffmpeg_path: str = "ffmpeg", model_dir: str = "cache/piper_models"):
        self._ffmpeg = ffmpeg_path
        self._model_dir = model_dir
        self._voice_id = "zh_CN-huayan-medium"
        os.makedirs(model_dir, exist_ok=True)

    @property
    def engine_name(self) -> str:
        return "Piper TTS (本地)"

    def list_voices(self) -> list[dict]:
        return PIPER_VOICES

    def test_connection(self) -> bool:
        try:
            from piper import PiperVoice
            return True
        except ImportError:
            return False

    def _ensure_model(self, voice_id: str) -> tuple[str, str]:
        """Download model if needed. Returns (model_path, config_path)."""
        model_path = os.path.join(self._model_dir, f"{voice_id}.onnx")
        config_path = model_path + ".json"

        if not os.path.isfile(model_path):
            logger.info(f"Downloading Piper model: {voice_id}...")
            import urllib.request

            # Parse voice ID: "zh_CN-huayan-medium" -> zh/zh_CN/huayan/medium/zh_CN-huayan-medium
            # or "en_US-lessac-medium" -> en/en_US/lessac/medium/en_US-lessac-medium
            parts = voice_id.split("-")
            if len(parts) >= 2:
                lang_full = parts[0]       # zh_CN
                name = parts[1]            # huayan
                quality = parts[2] if len(parts) > 2 else "medium"
                lang_short = lang_full.split("_")[0]  # zh
                url_path = f"{lang_short}/{lang_full}/{name}/{quality}/{voice_id}"
            else:
                url_path = f"zh/zh_CN/huayan/medium/{voice_id}"

            try:
                urllib.request.urlretrieve(
                    f"{MODEL_BASE}/{url_path}.onnx", model_path)
                urllib.request.urlretrieve(
                    f"{MODEL_BASE}/{url_path}.onnx.json", config_path)
                logger.info(f"Piper model downloaded: {voice_id}")
            except Exception as e:
                logger.error(f"Failed to download Piper model {voice_id}: {e}")
                # Remove partial download
                for p in [model_path, config_path]:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
                # Fall back to medium quality
                if quality != "medium" and lang_full == "zh_CN":
                    logger.info(f"Falling back to zh_CN-huayan-medium")
                    return self._ensure_model("zh_CN-huayan-medium")
                return "", ""

        return model_path, config_path

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
            from piper import PiperVoice

            voice = voice_id or self._voice_id
            model_path, config_path = self._ensure_model(voice)
            if not model_path or not os.path.isfile(model_path):
                logger.error(f"Piper model not available: {voice}")
                return False

            v = PiperVoice.load(model_path, config_path=config_path)

            # Synthesize to WAV bytes
            wav_buf = io.BytesIO()
            for chunk in v.synthesize(text):
                wav_buf.write(chunk.audio_int16_bytes)
            wav_data = wav_buf.getvalue()

            if not wav_data:
                logger.error("Piper TTS: empty output")
                return False

            # Write WAV
            import tempfile
            tmp_wav = os.path.join(tempfile.gettempdir(),
                                   f"_piper_{hash(text) & 0xFFFF}.wav")
            with wave.open(tmp_wav, "w") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(v.config.sample_rate)
                wf.writeframes(wav_data)

            # Convert to MP3
            if output_path:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                ok = wav_to_mp3(tmp_wav, output_path, self._ffmpeg)
                try:
                    os.remove(tmp_wav)
                except Exception:
                    pass
                if ok:
                    logger.info(f"Piper TTS: '{text[:30]}' -> {output_path}")
                return ok
            else:
                try:
                    os.remove(tmp_wav)
                except Exception:
                    pass
                return True

        except ImportError:
            logger.error("piper-tts not installed. pip install piper-tts")
            return False
        except Exception as e:
            logger.error(f"Piper TTS error: {e}")
            return False
