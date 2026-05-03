import os
import sys
import subprocess

from core.ffmpeg_service import FFmpegService
from core.audio_analyzer import AudioAnalyzer
from models.video_info_model import VideoInfoModel
from utils.audio_utils import adjust_mp3_volume
from utils.logger import get_logger

logger = get_logger()


class VideoComposer:
    def __init__(self, ffmpeg: FFmpegService | None = None):
        self._ffmpeg = ffmpeg or FFmpegService()
        self._analyzer = AudioAnalyzer(
            ffmpeg_path=self._ffmpeg.ffmpeg_path or "ffmpeg"
        )

    def analyze_source_video(self, video_path: str) -> VideoInfoModel:
        return self._ffmpeg.probe_video(video_path)

    def has_audio_stream(self, video_path: str) -> bool:
        info = self.analyze_source_video(video_path)
        return info.has_audio

    def analyze_loudness(self, media_path: str, duration: float = 3.0) -> dict:
        return self._analyzer.analyze_loudness(media_path, duration)

    def adjust_region_mp3_volume(
        self,
        source_video_path: str,
        region_mp3_path: str,
        output_mp3_path: str,
        target_offset_db: float = 3.0,
        max_gain_db: float = 8.0,
    ) -> str:
        """Adjust region MP3 volume to be target_offset_db above source video level."""
        try:
            src_loudness = self.analyze_loudness(source_video_path, duration=3.0)
            mp3_loudness = self.analyze_loudness(region_mp3_path, duration=0)

            src_mean = src_loudness.get("mean_volume_db", -20.0)
            mp3_mean = mp3_loudness.get("mean_volume_db", -20.0)

            # Desired: mp3_mean + gain = src_mean + target_offset_db
            desired_db = src_mean + target_offset_db
            gain_db = desired_db - mp3_mean

            # Clamp gain
            gain_db = max(-max_gain_db, min(max_gain_db, gain_db))
            gain_db = round(gain_db, 1)

            logger.info(
                f"Volume match: src={src_mean:.1f}dB, mp3={mp3_mean:.1f}dB, "
                f"gain={gain_db:.1f}dB"
            )

            os.makedirs(os.path.dirname(output_mp3_path), exist_ok=True)

            if abs(gain_db) < 0.5:
                import shutil
                shutil.copy2(region_mp3_path, output_mp3_path)
                return output_mp3_path

            ok = adjust_mp3_volume(
                region_mp3_path, output_mp3_path, gain_db,
                ffmpeg_path=self._ffmpeg.ffmpeg_path or "ffmpeg",
            )
            if not ok:
                logger.warning("Volume adjustment failed, using original")
                import shutil
                shutil.copy2(region_mp3_path, output_mp3_path)

            return output_mp3_path

        except Exception as e:
            logger.error(f"adjust_region_mp3_volume failed: {e}")
            import shutil
            shutil.copy2(region_mp3_path, output_mp3_path)
            return output_mp3_path

    def compose_final_video(
        self,
        source_video_path: str,
        region_gif_path: str,
        region_mp3_path: str,
        output_video_path: str,
        png_sequence_dir: str | None = None,
        gif_durations: list[int] | None = None,
        overlay_x: int = 0,
        overlay_y: int = 0,
        overlay_scale: float = 1.0,
    ) -> bool:
        if not self._ffmpeg.is_available:
            logger.error("FFmpeg not available")
            return False

        try:
            video_info = self.analyze_source_video(source_video_path)
            if video_info.duration <= 0:
                logger.error("Cannot determine source video duration")
                return False

            duration_str = str(video_info.duration)
            has_audio = video_info.has_audio
            ffmpeg_exe = self._ffmpeg.ffmpeg_path

            os.makedirs(os.path.dirname(output_video_path), exist_ok=True)

            # Calculate correct framerate for PNG sequence from GIF durations
            use_png = False
            if png_sequence_dir and os.path.isdir(png_sequence_dir):
                png_pattern = os.path.join(png_sequence_dir, "frame_%05d.png")
                if os.path.isfile(os.path.join(png_sequence_dir, "frame_00001.png")):
                    use_png = True
                    if gif_durations:
                        total_ms = sum(gif_durations)
                        frame_count = len(gif_durations)
                        png_fps = frame_count / (total_ms / 1000.0) if total_ms > 0 else 10
                    else:
                        png_fps = 10
                    overlay_input = ["-framerate", str(round(png_fps, 2)), "-i", png_pattern]

            if not use_png:
                overlay_input = ["-ignore_loop", "1", "-i", region_gif_path]

            cmd = [ffmpeg_exe, "-y", "-i", source_video_path]
            cmd.extend(overlay_input)
            cmd.extend(["-i", region_mp3_path])

            # Build overlay filter string with position and scale
            ox = int(overlay_x)
            oy = int(overlay_y)
            if abs(overlay_scale - 1.0) > 0.01:
                scale_filter = f"scale=iw*{overlay_scale}:ih*{overlay_scale},"
            else:
                scale_filter = ""

            if has_audio:
                filter_complex = (
                    f"[1:v]format=rgba,{scale_filter}setpts=PTS-STARTPTS[gifv];"
                    f"[0:v][gifv]overlay={ox}:{oy}:eof_action=pass:shortest=0[vout];"
                    "[0:a][2:a]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
                )
                cmd.extend(["-filter_complex", filter_complex, "-map", "[vout]", "-map", "[aout]"])
            else:
                cmd.extend([
                    "-f", "lavfi", "-t", duration_str,
                    "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                ])
                filter_complex = (
                    f"[1:v]format=rgba,{scale_filter}setpts=PTS-STARTPTS[gifv];"
                    f"[0:v][gifv]overlay={ox}:{oy}:eof_action=pass:shortest=0[vout];"
                    "[3:a][2:a]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
                )
                cmd.extend(["-filter_complex", filter_complex, "-map", "[vout]", "-map", "[aout]"])

            cmd.extend([
                "-t", duration_str,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-movflags", "+faststart",
                output_video_path,
            ])

            logger.info(f"FFmpeg compose: overlay=({ox},{oy}) scale={overlay_scale:.3f} filter={filter_complex[:120]}")

            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

            if result.returncode != 0:
                stderr_summary = result.stderr[-500:] if len(result.stderr) > 500 else result.stderr
                logger.error(f"FFmpeg failed (rc={result.returncode}): {stderr_summary}")
                return False

            if not os.path.isfile(output_video_path) or os.path.getsize(output_video_path) == 0:
                logger.error(f"Output video empty: {output_video_path}")
                return False

            out_info = self.analyze_source_video(output_video_path)
            if out_info.duration > 0 and abs(out_info.duration - video_info.duration) > 0.1:
                logger.warning(
                    f"Duration mismatch: expected {video_info.duration}s, got {out_info.duration}s"
                )

            logger.info(f"Final video composed: {output_video_path}")
            return True

        except Exception as e:
            logger.error(f"compose_final_video failed: {e}")
            return False
