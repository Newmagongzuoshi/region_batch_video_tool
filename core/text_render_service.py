from PIL import Image, ImageDraw, ImageFont, ImageFilter
from models.text_layer_model import TextLayerModel
from utils.logger import get_logger

logger = get_logger()

_FONT_CACHE: dict[str, ImageFont.FreeTypeFont] = {}

FALLBACK_FONTS = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

_BOLD_FONT_SUFFIXES = ["bd", "bold", "Bold", "BD"]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _get_font(font_size: int, font_family: str = "Microsoft YaHei",
              font_path: str | None = None, bold: bool = False) -> ImageFont.FreeTypeFont:
    cache_key = f"{font_path or font_family}_{font_size}_{'b' if bold else 'n'}"
    if cache_key in _FONT_CACHE:
        return _FONT_CACHE[cache_key]

    def _try_load(path: str, size: int) -> ImageFont.FreeTypeFont | None:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            return None

    # Use specified path or fallback chain
    base_path = font_path or font_family

    if bold:
        # Try bold variant: insert 'bd' before extension
        for suffix in _BOLD_FONT_SUFFIXES:
            if base_path.lower().endswith(('.ttf', '.ttc', '.otf')):
                for ext in ('.ttf', '.ttc', '.otf'):
                    bold_path = base_path[:-4] + suffix + ext
                    font = _try_load(bold_path, font_size)
                    if font:
                        _FONT_CACHE[cache_key] = font
                        return font

    # Normal load
    font = _try_load(base_path, font_size)
    if font:
        _FONT_CACHE[cache_key] = font
        return font

    # Fallback chain
    for fp in FALLBACK_FONTS:
        font = _try_load(fp, font_size)
        if font:
            _FONT_CACHE[cache_key] = font
            return font

    font = ImageFont.load_default()
    _FONT_CACHE[cache_key] = font
    return font


class TextRenderService:
    def render_text(self, text: str, layer: TextLayerModel) -> Image.Image | None:
        if not text:
            return None
        try:
            return self._render(text, layer)
        except Exception as e:
            logger.error(f"TextRenderService.render_text failed: {e}")
            return None

    def _render(self, text: str, layer: TextLayerModel) -> Image.Image:
        # Weight: use bold flag for font lookup, but also simulate heavier weights
        weight = getattr(layer, "weight", 700)
        use_bold = getattr(layer, "bold", True) or weight >= 600
        font = _get_font(layer.font_size, layer.font_family, layer.font_path, use_bold)
        # Extra horizontal offset for heavy weights (simulates bolder appearance)
        weight_offset = max(0, (weight - 600) // 200)  # 700→0, 900→1
        lines = text.split("\n")

        # Measure each line (accounting for letter spacing)
        line_sizes: list[tuple[int, int]] = []
        for line in lines:
            if layer.letter_spacing > 0:
                spaced_line = " ".join(line)  # approximate spacing
                bbox = font.getbbox(spaced_line)
            else:
                bbox = font.getbbox(line)
            lw = bbox[2] - bbox[0]
            lh = bbox[3] - bbox[1]
            line_sizes.append((lw, lh))

        text_w = max((w for w, _ in line_sizes), default=0)
        text_h = sum(h for _, h in line_sizes) + layer.line_spacing * max(0, len(lines) - 1)

        # Padding for effects
        stroke_pad = layer.stroke_width * 2 if layer.stroke_enabled else 0
        shadow_pad_x = abs(layer.shadow_offset_x) + layer.shadow_blur * 2 if layer.shadow_enabled else 0
        shadow_pad_y = abs(layer.shadow_offset_y) + layer.shadow_blur * 2 if layer.shadow_enabled else 0
        bg_pad = layer.background_padding + layer.border_width * 2 if layer.background_enabled else 0

        pad_left = max(stroke_pad, shadow_pad_x, bg_pad)
        pad_right = max(stroke_pad, shadow_pad_x, bg_pad)
        pad_top = max(stroke_pad, shadow_pad_y, bg_pad)
        pad_bottom = max(stroke_pad, shadow_pad_y, bg_pad)

        img_w = text_w + pad_left + pad_right + 10
        img_h = text_h + pad_top + pad_bottom + 10

        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Text origin (left edge of first line, relative to pad)
        origin_x = pad_left + 5
        origin_y = pad_top + 5

        # ---- background box ----
        if layer.background_enabled:
            bg_rgb = _hex_to_rgb(layer.background_color)
            bg_alpha = int(255 * layer.background_opacity)
            bg_x1 = origin_x - layer.background_padding
            bg_y1 = origin_y - layer.background_padding // 2
            bg_x2 = origin_x + text_w + layer.background_padding
            bg_y2 = origin_y + text_h + layer.background_padding // 2

            if layer.border_enabled:
                border_rgb = _hex_to_rgb(layer.border_color)
                border_alpha = int(255 * layer.border_opacity)
                border_pad = layer.border_width
                # Draw border (slightly larger rounded rect)
                draw.rounded_rectangle(
                    (bg_x1 - border_pad, bg_y1 - border_pad,
                     bg_x2 + border_pad, bg_y2 + border_pad),
                    radius=layer.background_radius + border_pad,
                    fill=(*border_rgb, border_alpha),
                )

            draw.rounded_rectangle(
                (bg_x1, bg_y1, bg_x2, bg_y2),
                radius=layer.background_radius,
                fill=(*bg_rgb, bg_alpha),
            )

        # ---- shadow ----
        if layer.shadow_enabled:
            shadow_rgb = _hex_to_rgb(layer.shadow_color)
            shadow_alpha = int(255 * layer.shadow_opacity)
            if layer.shadow_blur > 0:
                shadow_img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
                shadow_draw = ImageDraw.Draw(shadow_img)
                self._draw_text_lines(shadow_draw, lines, font, layer,
                                      origin_x + layer.shadow_offset_x,
                                      origin_y + layer.shadow_offset_y,
                                      text_w, line_sizes,
                                      color=(*shadow_rgb, shadow_alpha),
                                      weight_offset=0)
                shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(radius=layer.shadow_blur))
                img = Image.alpha_composite(img, shadow_img)
                draw = ImageDraw.Draw(img)  # must rebind after composite creates new image
            else:
                self._draw_text_lines(draw, lines, font, layer,
                                      origin_x + layer.shadow_offset_x,
                                      origin_y + layer.shadow_offset_y,
                                      text_w, line_sizes,
                                      color=(*shadow_rgb, shadow_alpha),
                                      weight_offset=0)

        # ---- stroke ----
        if layer.stroke_enabled:
            stroke_rgb = _hex_to_rgb(layer.stroke_color)
            stroke_alpha = int(255 * layer.opacity)
            sw = layer.stroke_width
            for dx in range(-sw, sw + 1):
                for dy in range(-sw, sw + 1):
                    if dx == 0 and dy == 0:
                        continue
                    self._draw_text_lines(draw, lines, font, layer,
                                          origin_x + dx, origin_y + dy,
                                          text_w, line_sizes,
                                          color=(*stroke_rgb, stroke_alpha),
                                          weight_offset=weight_offset)

        # ---- fill text ----
        fill_rgb = _hex_to_rgb(layer.fill_color)
        fill_alpha = int(255 * layer.opacity)

        if layer.gradient_enabled:
            start_rgb = _hex_to_rgb(layer.gradient_start)
            end_rgb = _hex_to_rgb(layer.gradient_end)
            self._draw_text_lines_gradient(draw, lines, font, layer,
                                           origin_x, origin_y,
                                           text_w, line_sizes,
                                           start_rgb, end_rgb, fill_alpha,
                                           weight_offset=weight_offset)
        else:
            self._draw_text_lines(draw, lines, font, layer,
                                  origin_x, origin_y,
                                  text_w, line_sizes,
                                  color=(*fill_rgb, fill_alpha),
                                  weight_offset=weight_offset)

        # Crop to content
        alpha = img.split()[-1]
        bbox = alpha.getbbox()
        if bbox:
            img = img.crop(bbox)
        return img

    # ---- line drawing helpers ----

    def _draw_text_lines(self, draw: ImageDraw.Draw, lines: list[str],
                         font, layer: TextLayerModel, base_x: int, base_y: int,
                         max_w: int, line_sizes: list[tuple[int, int]],
                         color: tuple, weight_offset: int = 0):
        cur_y = base_y
        for i, line in enumerate(lines):
            lw = line_sizes[i][0]
            x = self._align_x(base_x, lw, max_w, layer.align)
            y = cur_y
            txt = " ".join(line) if layer.letter_spacing > 0 else line
            for woff in range(weight_offset + 1):
                draw.text((x + woff, y), txt, font=font, fill=color)
            cur_y += line_sizes[i][1] + layer.line_spacing

    def _draw_text_lines_gradient(self, draw: ImageDraw.Draw, lines: list[str],
                                  font, layer: TextLayerModel,
                                  base_x: int, base_y: int,
                                  max_w: int, line_sizes: list[tuple[int, int]],
                                  start_rgb: tuple, end_rgb: tuple, alpha: int,
                                  weight_offset: int = 0):
        grad_type = getattr(layer, "gradient_type", "linear")
        direction = getattr(layer, "gradient_direction", "topToBottom")
        all_chars: list[tuple[str, int, int]] = []
        cur_y = base_y
        min_x, max_x_val = float("inf"), float("-inf")
        min_y, max_y_val = float("inf"), float("-inf")

        for i, line in enumerate(lines):
            lw = line_sizes[i][0]
            align_x = self._align_x(base_x, lw, max_w, layer.align)
            y = cur_y
            if layer.letter_spacing > 0:
                spaced_line = " ".join(line)
                chars = list(spaced_line)
                cx = align_x
            else:
                chars = list(line)
                cx = align_x
            for ch in chars:
                all_chars.append((ch, cx, y))
                min_x = min(min_x, cx)
                max_x_val = max(max_x_val, cx)
                min_y = min(min_y, y)
                max_y_val = max(max_y_val, y)
                bbox = font.getbbox(ch)
                cx += (bbox[2] - bbox[0])
            cur_y += line_sizes[i][1] + layer.line_spacing

        total = len(all_chars)
        text_w_range = max(1, max_x_val - min_x)
        text_h_range = max(1, max_y_val - min_y)

        # Center point for radial gradient
        cx_center = (min_x + max_x_val) / 2
        cy_center = (min_y + max_y_val) / 2
        max_radius = max(text_w_range, text_h_range) / 2

        for idx, (ch, cx, cy) in enumerate(all_chars):
            if grad_type == "radial":
                dx = cx - cx_center
                dy = cy - cy_center
                dist = (dx * dx + dy * dy) ** 0.5
                ratio = min(1.0, dist / max_radius)
            elif direction == "leftToRight":
                ratio = idx / max(total - 1, 1)
            elif direction == "leftTopToRightBot":
                ratio = ((cx - min_x) / text_w_range + (cy - min_y) / text_h_range) / 2
            elif direction == "rightTopToLeftBot":
                ratio = ((max_x_val - cx) / text_w_range + (cy - min_y) / text_h_range) / 2
            else:  # topToBottom
                ratio = (cy - min_y) / text_h_range
            ratio = max(0.0, min(1.0, ratio))
            r = int(start_rgb[0] + (end_rgb[0] - start_rgb[0]) * ratio)
            g = int(start_rgb[1] + (end_rgb[1] - start_rgb[1]) * ratio)
            b = int(start_rgb[2] + (end_rgb[2] - start_rgb[2]) * ratio)
            for woff in range(weight_offset + 1):
                draw.text((cx + woff, cy), ch, font=font, fill=(r, g, b, alpha))

    @staticmethod
    def _align_x(base_x: int, line_w: int, max_w: int, align: str) -> int:
        if align == "center":
            return base_x + (max_w - line_w) // 2
        elif align == "right":
            return base_x + max_w - line_w
        return base_x  # left
