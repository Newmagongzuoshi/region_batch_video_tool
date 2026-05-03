from dataclasses import dataclass


@dataclass
class TaskModel:
    id: int = 0
    region: str = ""
    safe_filename: str = ""
    gif_status: str = "pending"
    mp3_status: str = "pending"
    mp4_status: str = "pending"
    gif_path: str = ""
    mp3_path: str = ""
    mp4_path: str = ""
    error_message: str | None = None
    retry_count: int = 0
    updated_at: str = ""
