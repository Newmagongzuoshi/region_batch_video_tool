from dataclasses import dataclass


@dataclass
class RegionModel:
    original_name: str
    clean_name: str
    safe_filename: str
    line_number: int
