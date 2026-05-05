import logging
import os
from datetime import datetime

from utils.path_utils import resolve_data_path, ensure_dir

_logger: logging.Logger | None = None


def setup_logging(log_dir: str | None = None) -> logging.Logger:
    global _logger

    if log_dir is None:
        log_dir = resolve_data_path("logs")
    ensure_dir(log_dir)

    logger = logging.getLogger("region_batch_video_tool")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(
        os.path.join(log_dir, "app.log"), encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    _logger = logger
    logger.info("Logger initialized")
    return logger


def get_logger() -> logging.Logger:
    if _logger is None:
        return setup_logging()
    return _logger
