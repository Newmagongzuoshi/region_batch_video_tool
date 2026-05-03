import os
import sys
import subprocess
import tempfile

from core.tts_engine_base import BaseTTSEngine
from utils.audio_utils import wav_to_mp3
from utils.logger import get_logger

logger = get_logger()


class WindowsSapiTTSEngine(BaseTTSEngine):
    """Windows SAPI TTS via PowerShell/.NET SpeechSynthesizer.

    Uses a separate PowerShell process for each synthesis call,
    completely avoiding COM threading issues that pyttsx3 has.
    """

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self._ffmpeg = ffmpeg_path
        self._voices: list[dict] = []
        self._voice: str = ""
        self._init_voices()

    def _init_voices(self):
        """List available voices using PowerShell."""
        try:
            ps_script = (
                'Add-Type -AssemblyName System.Speech;'
                '$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;'
                '$s.GetInstalledVoices() | ForEach-Object { '
                '$v = $_.VoiceInfo; '
                'Write-Host ($v.Name + "|" + $v.Culture.Name + "|" + $v.Gender) '
                '}'
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if "|" in line:
                    parts = line.split("|")
                    self._voices.append({
                        "id": parts[0], "name": parts[0],
                        "culture": parts[1] if len(parts) > 1 else "",
                    })
            logger.info(f"Found {len(self._voices)} SAPI voices via PowerShell")
        except Exception as e:
            logger.error(f"Failed to list voices: {e}")
            self._voices = [
                {"id": "default", "name": "Default Voice", "culture": ""}
            ]

    @property
    def engine_name(self) -> str:
        return "Windows SAPI5 (PowerShell)"

    def list_voices(self) -> list[dict]:
        return self._voices

    def test_connection(self) -> bool:
        return len(self._voices) > 0

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

        try:
            tmp_dir = tempfile.gettempdir()
            wav_path = os.path.join(tmp_dir, f"_rbvt_tts_{abs(hash(text)) % 100000}.wav")

            # Escape text for PowerShell
            safe_text = text.replace('"', '""').replace('\n', ' ').replace('\r', '')

            voice_cmd = ""
            vid = voice_id or self._voice
            if vid:
                safe_voice = vid.replace('"', '""')
                voice_cmd = f'$s.SelectVoice("{safe_voice}");'

            rate = int((speed - 1.0) * 10)  # -10 to 10
            vol = int(volume * 100)

            ps_script = (
                'Add-Type -AssemblyName System.Speech;'
                f'$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;'
                f'{voice_cmd}'
                f'$s.Rate = {rate};'
                f'$s.Volume = {vol};'
                f'$s.SetOutputToWaveFile("{wav_path}");'
                f'$s.Speak("{safe_text}");'
                f'$s.Dispose();'
                f'Write-Host "OK"'
            )

            logger.info(f"TTS: speaking '{text[:40]}' (rate={rate}, vol={vol})")

            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            if result.returncode != 0 or "OK" not in result.stdout:
                logger.error(f"PowerShell TTS failed: rc={result.returncode}, "
                             f"stderr={result.stderr[:200]}")
                return False

            if not os.path.isfile(wav_path) or os.path.getsize(wav_path) < 100:
                logger.error(f"WAV file not created or too small: {wav_path}")
                return False

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            ok = wav_to_mp3(wav_path, output_path, self._ffmpeg)

            try:
                os.remove(wav_path)
            except Exception:
                pass

            if ok:
                logger.info(f"TTS OK: '{text[:30]}' -> {output_path}")
            return ok

        except subprocess.TimeoutExpired:
            logger.error(f"TTS timeout for: {text[:40]}")
            return False
        except Exception as e:
            logger.error(f"TTS exception: {e}")
            return False
