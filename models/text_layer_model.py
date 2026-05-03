from dataclasses import dataclass, field


@dataclass
class TextLayerModel:
    text_template: str = "{地区}"
    x: float = 0.0
    y: float = 0.0
    anchor: str = "top_left"
    font_family: str = "Microsoft YaHei"
    font_path: str | None = None
    font_size: int = 48
    template_id: str = ""
    fill_color: str = "#FFFFFF"
    stroke_enabled: bool = False
    stroke_color: str = "#000000"
    stroke_width: int = 3
    shadow_enabled: bool = False
    shadow_color: str = "#000000"
    shadow_offset_x: int = 3
    shadow_offset_y: int = 3
    shadow_blur: int = 4
    gradient_enabled: bool = False
    gradient_start: str = "#FFFFFF"
    gradient_end: str = "#FFD700"
    background_enabled: bool = False
    background_color: str = "#000000"
    background_radius: int = 12
    opacity: float = 1.0
    letter_spacing: int = 0
    line_spacing: int = 8
    max_width: int | None = None
    align: str = "left"
    center_horizontal: bool = True
