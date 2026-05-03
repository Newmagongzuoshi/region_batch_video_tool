from dataclasses import dataclass, field


@dataclass
class TTSEngineConfig:
    config_id: str
    display_name: str
    provider: str
    enabled: bool = True
    endpoint: str = ""
    secret_ref: str = ""
    method: str = "POST"
    headers: dict = field(default_factory=dict)
    body: dict = field(default_factory=dict)
    response_type: str = "binary"
    base64_field: str = ""
    url_field: str = ""
    default_voice_id: str = ""


@dataclass
class TTSConfig:
    default_engine: str = "windows_sapi"
    default_voice_id: str = ""
    speed: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0
    api_configs: list[TTSEngineConfig] = field(default_factory=list)
