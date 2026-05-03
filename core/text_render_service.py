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


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _get_font(font_size: int, font_family: str = "Microsoft YaHei",
              font_path: str | None = None) -> ImageFont.FreeTypeFont:
    cache_key = f"{font_path or font_family}_{font_size}"
    if cache_key in _FONT_CACHE:
        return _FONT_CACHE[cache_key]

    if font_path:
        try:
            font = ImageFont.truetype(font_path, font_size)
            _FONT_CACHE[cache_key] = font
            return font
        except Exception:
            logger.warning(f"Font path failed: {font_path}")

    # Try font_family as a path
    for candidate in [font_family] + FALLBACK_FONTS:
        try:
            font = ImageFont.truetype(candidate, font_size)
            _FONT_CACHE[cache_key] = font
            return font
        except Exception:
            continue

    # Final fallback
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
        font = _get_font(layer.font_size, layer.font_family, layer.font_path)
        fill_rgb = _hex_to_rgb(layer.fill_color)

        # Calculate text size
        bbox = font.getbbox(text)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        # Padding for stroke, shadow, etc.
        stroke_pad = layer.stroke_width * 2 if layer.stroke_enabled else 0
        shadow_pad_x = abs(layer.shadow_offset_x) + layer.shadow_blur * 2 if layer.shadow_enabled else 0
        shadow_pad_y = abs(layer.shadow_offset_y) + layer.shadow_blur * 2 if layer.shadow_enabled else 0
        bg_pad = 20 if layer.background_enabled else 0

        pad_left = max(stroke_pad, shadow_pad_x, bg_pad)
        pad_right = max(stroke_pad, shadow_pad_x, bg_pad)
        pad_top = max(stroke_pad, shadow_pad_y, bg_pad)
        pad_bottom = max(stroke_pad, shadow_pad_y, bg_pad)

        img_w = text_w + pad_left + pad_right + 10
        img_h = text_h + pad_top + pad_bottom + 10

        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Text anchor position (center-left)
        x = pad_left + 5
        y = pad_top + 5

        # Draw shadow
        if layer.shadow_enabled:
            shadow_rgb = _hex_to_rgb(layer.shadow_color)
            shadow_x = x + layer.shadow_offset_x
            shadow_y = y + layer.shadow_offset_y
            if layer.shadow_blur > 0:
                shadow_img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
                shadow_draw = ImageDraw.Draw(shadow_img)
                shadow_draw.text(
                    (shadow_x, shadow_y), text, font=font,
                    fill=(*shadow_rgb, int(255 * layer.opacity))
                )
                shadow_img = shadow_img.filter(
                    ImageFilter.GaussianBlur(radius=layer.shadow_blur)
                )
                img = Image.alpha_composite(img, shadow_img)
            else:
                draw.text(
                    (shadow_x, shadow_y), text, font=font,
                    fill=(*shadow_rgb, int(255 * layer.opacity))
                )

        # Draw background
        if layer.background_enabled:
            bg_rgb = _hex_to_rgb(layer.background_color)
            bg_x1 = x - layer.background_radius
            bg_y1 = y - layer.background_radius // 2
            bg_x2 = x + text_w + layer.background_radius
            bg_y2 = y + text_h + layer.background_radius // 2
            draw.rounded_rectangle(
                (bg_x1, bg_y1, bg_x2, bg_y2),
                radius=layer.background_radius,
                fill=(*bg_rgb, int(255 * layer.opacity * 0.85))
            )

        # Draw stroke (multiple passes)
        if layer.stroke_enabled:
            stroke_rgb = _hex_to_rgb(layer.stroke_color)
            sw = layer.stroke_width
            for dx in range(-sw, sw + 1):
                for dy in range(-sw, sw + 1):
                    if dx == 0 and dy == 0:
                        continue
                    draw.text(
                        (x + dx, y + dy), text, font=font,
                        fill=(*stroke_rgb, int(255 * layer.opacity))
                    )

        # Gradient fill or solid fill
        if layer.gradient_enabled:
            start_rgb = _hex_to_rgb(layer.gradient_start)
            end_rgb = _hex_to_rgb(layer.gradient_end)
            for i, ch in enumerate(text):
                char_x = x + font.getbbox(text[:i])[2] if i > 0 else x
                ratio = i / max(len(text) - 1, 1)
                r = int(start_rgb[0] + (end_rgb[0] - start_rgb[0]) * ratio)
                g = int(start_rgb[1] + (end_rgb[1] - start_rgb[1]) * ratio)
                b = int(start_rgb[2] + (end_rgb[2] - start_rgb[2]) * ratio)
                draw.text((char_x, y), ch, font=font,
                          fill=(r, g, b, int(255 * layer.opacity)))
        else:
            draw.text((x, y), text, font=font,
                      fill=(*fill_rgb, int(255 * layer.opacity)))

        # Crop to content
        alpha = img.split()[-1]
        bbox = alpha.getbbox()
        if bbox:
            img = img.crop(bbox)

        return img
