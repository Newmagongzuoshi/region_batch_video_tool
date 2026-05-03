from dataclasses import dataclass


@dataclass
class VideoInfoModel:
    width: int = 0
    height: int = 0
    fps: float = 0.0
    duration: float = 0.0
    has_audio: bool = False
    audio_sample_rate: int = 0
    audio_channels: int = 0
    codec: str = ""
