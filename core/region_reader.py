import os
import re

from models.region_model import RegionModel
from utils.path_utils import safe_filename
from utils.logger import get_logger

logger = get_logger()


class RegionReader:
    def __init__(self):
        self._regions: list[RegionModel] = []

    def load(self, txt_path: str) -> list[RegionModel]:
        self._regions.clear()
        seen = set()

        if not os.path.isfile(txt_path):
            logger.error(f"Region file not found: {txt_path}")
            return []

        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(txt_path, "r", encoding="gbk") as f:
                lines = f.readlines()

        for line_num, line in enumerate(lines, start=1):
            original = line.strip()
            if not original:
                continue
            clean_name = original
            safe = safe_filename(original)
            if safe != original:
                logger.info(f"Line {line_num}: '{original}' -> filename '{safe}'")

            if clean_name in seen:
                logger.info(f"Line {line_num}: duplicate '{clean_name}' skipped")
                continue
            seen.add(clean_name)

            self._regions.append(RegionModel(
                original_name=original,
                clean_name=clean_name,
                safe_filename=safe,
                line_number=line_num,
            ))

        logger.info(f"Loaded {len(self._regions)} unique regions from {txt_path}")
        return self._regions

    @property
    def regions(self) -> list[RegionModel]:
        return list(self._regions)

    @property
    def count(self) -> int:
        return len(self._regions)
