from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TextLayerModel:
    # Content
    text_template: str = "{地区}"

    # Position
    x: float = 0.0
    y: float = 0.0
    center_horizontal: bool = True

    # Font
    font_family: str = "Microsoft YaHei"
    font_path: str | None = None
    font_size: int = 72
    bold: bool = True
    italic: bool = False
    weight: int = 700  # 100-900
    letter_spacing: int = 0
    line_spacing: int = 8
    align: str = "center"  # left / center / right
    fill_color: str = "#FFD700"
    opacity: float = 1.0

    # Stroke
    stroke_enabled: bool = True
    stroke_color: str = "#000000"
    stroke_width: int = 8
    stroke_opacity: float = 1.0

    # Shadow
    shadow_enabled: bool = True
    shadow_color: str = "#000000"
    shadow_opacity: float = 0.5
    shadow_offset_x: int = 3
    shadow_offset_y: int = 3
    shadow_blur: int = 4

    # Gradient
    gradient_enabled: bool = False
    gradient_start: str = "#FFFFFF"
    gradient_mid: str = ""  # optional mid-stop; empty=2-stop gradient
    gradient_end: str = "#FFD700"
    gradient_type: str = "linear"  # linear | radial
    gradient_midpoint: float = 0.5  # 0.0-1.0, controls where the color transition happens
    gradient_direction: str = "topToBottom"  # leftToRight | topToBottom | leftTopToRightBot | rightTopToLeftBot

    # Background box
    background_enabled: bool = False
    background_color: str = "#000000"
    background_opacity: float = 0.6
    background_radius: int = 12
    background_padding: int = 12

    # Background border
    border_enabled: bool = False
    border_color: str = "#FFFFFF"
    border_width: int = 2
    border_opacity: float = 1.0

    # Guides & Snap
    guide_enabled: bool = True
    snap_enabled: bool = True
    safe_area_enabled: bool = False

    # Meta
    template_id: str = ""
    anchor: str = "center"  # topLeft/topCenter/topRight/centerLeft/center/centerRight/bottomLeft/bottomCenter/bottomRight
    max_width: int | None = None

    def clone(self) -> TextLayerModel:
        """Return a deep copy for undo stack."""
        return TextLayerModel(
            text_template=self.text_template,
            x=self.x, y=self.y, center_horizontal=self.center_horizontal,
            font_family=self.font_family, font_path=self.font_path,
            font_size=self.font_size, bold=self.bold, italic=self.italic,
            weight=self.weight, letter_spacing=self.letter_spacing, line_spacing=self.line_spacing,
            align=self.align, fill_color=self.fill_color, opacity=self.opacity,
            stroke_enabled=self.stroke_enabled, stroke_color=self.stroke_color,
            stroke_width=self.stroke_width, stroke_opacity=self.stroke_opacity,
            shadow_enabled=self.shadow_enabled, shadow_color=self.shadow_color,
            shadow_opacity=self.shadow_opacity, shadow_offset_x=self.shadow_offset_x,
            shadow_offset_y=self.shadow_offset_y, shadow_blur=self.shadow_blur,
            gradient_enabled=self.gradient_enabled, gradient_start=self.gradient_start,
            gradient_mid=self.gradient_mid, gradient_end=self.gradient_end,
            gradient_type=self.gradient_type, gradient_midpoint=self.gradient_midpoint,
            gradient_direction=self.gradient_direction,
            background_enabled=self.background_enabled, background_color=self.background_color,
            background_opacity=self.background_opacity, background_radius=self.background_radius,
            background_padding=self.background_padding,
            border_enabled=self.border_enabled, border_color=self.border_color,
            border_width=self.border_width, border_opacity=self.border_opacity,
            guide_enabled=self.guide_enabled, snap_enabled=self.snap_enabled,
            safe_area_enabled=self.safe_area_enabled,
            template_id=self.template_id, anchor=self.anchor, max_width=self.max_width,
        )
