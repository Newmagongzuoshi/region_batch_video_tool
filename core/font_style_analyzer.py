"""Analyze a selected image region to produce an independent flower-text style JSON.

This module does NOT:
- Match against any existing template library
- Recognize font names
- OCR text content
- Call any online API

It ONLY analyzes pixel data in the selected region.
"""

from __future__ import annotations

import colorsys
import json
import os
import time
from collections import Counter
from statistics import mode

from PIL import Image


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02X}{g:02X}{b:02X}"


def _color_distance(c1: tuple, c2: tuple) -> float:
    return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2) ** 0.5


def _luminance(rgb: tuple) -> float:
    return rgb[0] * 0.299 + rgb[1] * 0.587 + rgb[2] * 0.114


def _is_dark(rgb: tuple) -> bool:
    return _luminance(rgb) < 128


def _hue(rgb: tuple) -> float:
    r, g, b = [c / 255.0 for c in rgb]
    mx = max(r, g, b)
    mn = min(r, g, b)
    if mx == mn:
        return 0
    d = mx - mn
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60


def _cluster_colors(pixels: list[tuple], k: int = 3, max_iter: int = 10) -> list[tuple]:
    if len(pixels) < k:
        return [pixels[0]] if pixels else [(0, 0, 0)]
    n = len(pixels)
    centroids = [pixels[i * n // k] for i in range(k)]
    for _ in range(max_iter):
        clusters: list[list[tuple]] = [[] for _ in range(k)]
        for p in pixels:
            best = min(range(k), key=lambda i: _color_distance(p, centroids[i]))
            clusters[best].append(p)
        new_centroids = []
        for i, cl in enumerate(clusters):
            if cl:
                avg_r = sum(p[0] for p in cl) // len(cl)
                avg_g = sum(p[1] for p in cl) // len(cl)
                avg_b = sum(p[2] for p in cl) // len(cl)
                new_centroids.append((avg_r, avg_g, avg_b))
            else:
                new_centroids.append(centroids[i])
        if all(_color_distance(c, nc) < 2 for c, nc in zip(centroids, new_centroids)):
            break
        centroids = new_centroids
    return centroids


# ---------------------------------------------------------------------------
# main analyzer
# ---------------------------------------------------------------------------

def analyze_text_style(image: Image.Image,
                       region: tuple[int, int, int, int] | None = None,
                       style_id: str = "",
                       source_image: str = "") -> dict:
    """Analyze a text region and produce an independent flower-text style JSON.

    Returns a dict matching the custom_styles JSON schema.
    """
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    if region:
        rx, ry, rw, rh = region
        crop = image.crop((rx, ry, rx + rw, ry + rh))
    else:
        crop = image.copy()
        rx, ry, rw, rh = 0, 0, crop.width, crop.height

    src_w, src_h = crop.size
    if src_w < 4 or src_h < 4:
        return _default_style(style_id, source_image, rx, ry, rw, rh)

    pixels = crop.load()
    total_pixels = src_w * src_h

    # ---- classify by alpha ----
    bg_rgb: list[tuple] = []               # a < 15      — fully transparent
    opaque_pos: list[tuple[int, int]] = []  # a > 220     — fully opaque
    aa_edge_rgb: list[tuple] = []           # 15 <= a <= 220 — anti-aliased edge
    all_fg_pos: list[tuple[int, int]] = []
    solid_pixels: list[tuple] = []          # all pixels for solid-bg fallback

    for py in range(src_h):
        for px in range(src_w):
            r, g, b, a = pixels[px, py]
            solid_pixels.append((r, g, b))
            if a < 15:
                bg_rgb.append((r, g, b))
            elif a > 220:
                opaque_pos.append((px, py))
                all_fg_pos.append((px, py))
            else:
                aa_edge_rgb.append((r, g, b))
                all_fg_pos.append((px, py))

    # Detect solid-background images: if < 5% of pixels are transparent
    transparent_ratio = (total_pixels - len(all_fg_pos)) / total_pixels if total_pixels > 0 else 1.0
    is_solid_bg = transparent_ratio < 0.05

    if is_solid_bg and solid_pixels:
        # Solid background — reset and use color clustering
        all_fg_pos.clear()
        opaque_pos.clear()
        aa_edge_rgb.clear()
        bg_rgb.clear()

        clusters = _cluster_colors(solid_pixels, k=3)
        cluster_counts = [0] * len(clusters)
        for c in solid_pixels:
            best = min(range(len(clusters)), key=lambda i: _color_distance(c, clusters[i]))
            cluster_counts[best] += 1
        bg_idx = max(range(len(clusters)), key=lambda i: cluster_counts[i])

        fg_threshold = 50
        for py in range(src_h):
            for px in range(src_w):
                r, g, b, a = pixels[px, py]
                c = (r, g, b)
                if _color_distance(c, clusters[bg_idx]) > fg_threshold:
                    all_fg_pos.append((px, py))
                    if a > 200:
                        opaque_pos.append((px, py))
                    else:
                        aa_edge_rgb.append(c)
                else:
                    bg_rgb.append(c)

    if not all_fg_pos:
        return _default_style(style_id, source_image, rx, ry, rw, rh)

    min_x = min(px for px, _ in all_fg_pos)
    max_x = max(px for px, _ in all_fg_pos)
    min_y = min(py for _, py in all_fg_pos)
    max_y = max(py for _, py in all_fg_pos)

    # Build fast lookup set for foreground positions
    fg_set = set(all_fg_pos)

    # ---- distance-based separation of opaque pixels ----
    # Compute distance from each opaque pixel to the nearest non-opaque pixel.
    # Pixels at distance 1-2 are boundary (stroke); distance > 2 are interior (body).
    opaque_set = set(opaque_pos)
    # Build a distance map using simple iterative dilation
    dist: dict[tuple[int, int], int] = {}
    # Init: boundary pixels (neighbor is non-opaque) get dist=1
    frontier: list[tuple[int, int]] = []
    for px, py in opaque_pos:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                if (px + dx, py + dy) not in opaque_set:
                    dist[(px, py)] = 1
                    frontier.append((px, py))
                    break
            else:
                continue
            break
    # BFS inward
    cur_dist = 1
    max_dist = max(3, min(src_w, src_h) // 8)
    while frontier and cur_dist < max_dist:
        cur_dist += 1
        next_frontier: list[tuple[int, int]] = []
        for px, py in frontier:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    np = (px + dx, py + dy)
                    if np in opaque_set and np not in dist:
                        dist[np] = cur_dist
                        next_frontier.append(np)
        frontier = next_frontier

    # ---- Separate stroke vs body by distance; use distance-weighted fill detection ----
    body_threshold = max(2, min(4, (max_x - min_x) // 12, (max_y - min_y) // 12))
    stroke_pos: list[tuple[int, int]] = []
    body_pos: list[tuple[int, int]] = []

    for px, py in opaque_pos:
        d = dist.get((px, py), max_dist)
        if d <= body_threshold:
            stroke_pos.append((px, py))
        else:
            body_pos.append((px, py))

    # ---- fill color: use body pixels (deep interior), fallback weighted all opaque ----
    if body_pos:
        # Body pixels = deep interior, most representative of fill color
        body_colors = [pixels[px, py][:3] for px, py in body_pos]
        fill_counter = Counter(body_colors)
        fill_rgb = fill_counter.most_common(1)[0][0]
    elif opaque_pos:
        # No body pixels (very thin text or thick stroke) — distance-weighted voting
        weighted: dict[tuple, float] = {}
        for px, py in opaque_pos:
            c = pixels[px, py][:3]
            d = dist.get((px, py), 1)
            w = d * d  # square distance weight (far pixels dominate)
            weighted[c] = weighted.get(c, 0.0) + w
        fill_rgb = max(weighted, key=weighted.get) if weighted else (255, 255, 255)
    elif aa_edge_rgb:
        fill_counter = Counter(aa_edge_rgb)
        fill_rgb = fill_counter.most_common(1)[0][0]
    else:
        fill_rgb = (255, 255, 255)

    # ---- outline (stroke) detection ----
    outline_enabled = False
    outline_rgb = (0, 0, 0)
    outline_width = 0

    # Higher thresholds for solid backgrounds (anti-aliasing creates false edges)
    dist_threshold = 40 if is_solid_bg else 30

    if stroke_pos and body_pos and len(stroke_pos) >= 4:
        stroke_colors = [pixels[px, py][:3] for px, py in stroke_pos]
        stroke_counter = Counter(stroke_colors)
        # Find a stroke color that clearly differs from fill
        candidates = [(c, n) for c, n in stroke_counter.most_common(5)
                      if _color_distance(c, fill_rgb) > dist_threshold]
        if candidates:
            outline_enabled = True
            outline_rgb = candidates[0][0]
            ratio = len(stroke_pos) / max(1, len(stroke_pos) + len(body_pos))
            outline_width = max(2, min(12, round(ratio * 20)))
    elif aa_edge_rgb and len(aa_edge_rgb) >= 4:
        # Fallback: check anti-aliased edge
        aa_counter = Counter(aa_edge_rgb)
        candidates = [(c, n) for c, n in aa_counter.most_common(5)
                      if _color_distance(c, fill_rgb) > dist_threshold]
        # Only flag stroke if it constitutes a real border (at least 12% of FG)
        if candidates:
            aa_ratio = len(aa_edge_rgb) / max(1, len(opaque_pos) + len(aa_edge_rgb))
            if aa_ratio >= 0.12:
                outline_enabled = True
                outline_rgb = candidates[0][0]
                outline_width = 2

    # ---- shadow detection ----
    shadow_enabled = False
    shadow_rgb = (0, 0, 0)
    shadow_dx = 0
    shadow_dy = 0

    if len(all_fg_pos) > 20:
        light_pos = [(px, py) for px, py in all_fg_pos
                     if not _is_dark(pixels[px, py][:3])]
        dark_pos = [(px, py) for px, py in all_fg_pos
                    if _is_dark(pixels[px, py][:3])]

        if light_pos and dark_pos and len(dark_pos) >= 8:
            light_cx = sum(p[0] for p in light_pos) / len(light_pos)
            light_cy = sum(p[1] for p in light_pos) / len(light_pos)
            dark_cx = sum(p[0] for p in dark_pos) / len(dark_pos)
            dark_cy = sum(p[1] for p in dark_pos) / len(dark_pos)

            dx = round(dark_cx - light_cx)
            dy = round(dark_cy - light_cy)
            if abs(dx) >= 2 or abs(dy) >= 2:
                shadow_enabled = True
                shadow_dx = max(-20, min(20, dx))
                shadow_dy = max(-20, min(20, dy))
                dark_counter = Counter(pixels[px, py][:3] for px, py in dark_pos)
                shadow_rgb = dark_counter.most_common(1)[0][0]

    # ---- gradient detection ----
    gradient_enabled = False
    grad_start = fill_rgb
    grad_end = fill_rgb

    # Use body_pos (or opaque_pos as fallback) for gradient detection
    grad_pool = body_pos if body_pos else opaque_pos
    if len(grad_pool) > 30:
        band_h = max(2, (max_y - min_y) // 5)
        top_band = [(px, py) for px, py in grad_pool if py <= min_y + band_h]
        bot_band = [(px, py) for px, py in grad_pool if py >= max_y - band_h]
        if len(top_band) >= 5 and len(bot_band) >= 5:
            def _avg(positions):
                rs = sum(pixels[px, py][0] for px, py in positions) // len(positions)
                gs = sum(pixels[px, py][1] for px, py in positions) // len(positions)
                bs = sum(pixels[px, py][2] for px, py in positions) // len(positions)
                return (rs, gs, bs)
            top_avg = _avg(top_band)
            bot_avg = _avg(bot_band)
            if _color_distance(top_avg, bot_avg) > 25:
                gradient_enabled = True
                grad_start = top_avg
                grad_end = bot_avg

    # ---- glow detection ----
    # Glow: pixels outside the text with similar hue to fill but low opacity
    glow_enabled = False
    glow_rgb = fill_rgb
    glow_radius = 0

    if bg_rgb and opaque_pos and len(aa_edge_rgb) > 10:
        fill_hue = _hue(fill_rgb)
        # Check for background pixels with similar hue to fill color near the text boundary
        glow_candidates = [
            (r, g, b) for r, g, b in bg_rgb
            if _luminance((r, g, b)) > 30 and abs(_hue((r, g, b)) - fill_hue) < 40
        ]
        if len(glow_candidates) > len(bg_rgb) * 0.15:
            glow_enabled = True
            glow_counter = Counter(glow_candidates)
            glow_rgb = glow_counter.most_common(1)[0][0]
            glow_radius = max(2, min(15, round(len(glow_candidates) / max(1, len(bg_rgb)) * 10)))

    # ---- texture detection ----
    texture_enabled = False
    tex_pool = body_pos if body_pos else opaque_pos
    if len(tex_pool) > 50:
        tex_colors = [pixels[px, py][:3] for px, py in tex_pool]
        unique_colors = len(set(tex_colors))
        ratio = unique_colors / len(tex_colors)
        if ratio > 0.3:
            texture_enabled = True

    # ---- background box detection ----
    bg_box_enabled = False
    bg_box_rgb = (0, 0, 0)
    if bg_rgb and len(bg_rgb) > 20:
        bg_counter = Counter(bg_rgb)
        dominant_bg = bg_counter.most_common(1)[0][0]
        dom_ratio = bg_counter[dominant_bg] / len(bg_rgb)
        if dom_ratio > 0.35 and _color_distance(dominant_bg, (0, 0, 0)) > 40:
            bg_box_enabled = True
            bg_box_rgb = dominant_bg

    # ---- derived fields ----
    effect_count = sum([outline_enabled, shadow_enabled, gradient_enabled, glow_enabled, texture_enabled, bg_box_enabled])

    keywords: list[str] = []
    if outline_enabled:
        keywords.append("描边")
    if shadow_enabled:
        keywords.append("阴影")
    if gradient_enabled:
        keywords.append("渐变")
    if glow_enabled:
        keywords.append("发光")
    if texture_enabled:
        keywords.append("纹理")
    if bg_box_enabled:
        keywords.append("底色框")
    if outline_width >= 6:
        keywords.append("粗描边")
    if _is_dark(fill_rgb):
        keywords.append("深色字")
    else:
        keywords.append("亮色字")

    complexity = "simple" if effect_count <= 1 else ("medium" if effect_count <= 3 else "complex")
    decoration = "minimal" if effect_count <= 1 else ("moderate" if effect_count <= 3 else "heavy")

    visual_desc = _build_visual_desc(fill_rgb, outline_enabled, outline_rgb,
                                     shadow_enabled, shadow_rgb, shadow_dx, shadow_dy,
                                     gradient_enabled, glow_enabled, bg_box_enabled, bg_box_rgb)

    prompt = _build_prompt(fill_rgb, outline_enabled, outline_rgb, outline_width,
                          shadow_enabled, shadow_rgb, shadow_dx, shadow_dy,
                          gradient_enabled, grad_start, grad_end,
                          glow_enabled, bg_box_enabled)

    return {
        "style_id": style_id,
        "style_name": "用户框选花字样式",
        "source_image": source_image,
        "cropped_image": "",
        "selected_region": {"x": rx, "y": ry, "width": rw, "height": rh},
        "style_type": "custom_flower_text",
        "colors": {
            "fill_color": _rgb_to_hex(*fill_rgb),
            "outline_color": _rgb_to_hex(*outline_rgb) if outline_enabled else "",
            "shadow_color": _rgb_to_hex(*shadow_rgb) if shadow_enabled else "",
            "background_color": _rgb_to_hex(*bg_box_rgb) if bg_box_enabled else "",
        },
        "effects": {
            "has_outline": outline_enabled,
            "outline_width": outline_width,
            "has_shadow": shadow_enabled,
            "shadow_offset": [shadow_dx, shadow_dy],
            "shadow_blur": 4 if shadow_enabled else 0,
            "has_gradient": gradient_enabled,
            "has_glow": glow_enabled,
            "has_texture": texture_enabled,
        },
        "style_features": {
            "keywords": keywords,
            "complexity": complexity,
            "decoration_level": decoration,
            "visual_description": visual_desc,
        },
        "render_config": {
            "fill": {"color": _rgb_to_hex(*fill_rgb)},
            "outline": {
                "color": _rgb_to_hex(*outline_rgb),
                "width": outline_width,
            } if outline_enabled else None,
            "shadow": {
                "color": _rgb_to_hex(*shadow_rgb),
                "offset": [shadow_dx, shadow_dy],
                "blur": 4,
            } if shadow_enabled else None,
            "effects": {
                "gradient": {
                    "start": _rgb_to_hex(*grad_start),
                    "end": _rgb_to_hex(*grad_end),
                } if gradient_enabled else None,
                "glow": {
                    "color": _rgb_to_hex(*glow_rgb),
                    "radius": glow_radius,
                } if glow_enabled else None,
                "texture": {"type": "unknown"} if texture_enabled else None,
            },
        },
        "prompt": prompt,
    }


# ---------------------------------------------------------------------------
# description / prompt builders
# ---------------------------------------------------------------------------

_CN_COLORS: list[tuple[str, tuple]] = [
    ("白色", (255, 255, 255)), ("黑色", (0, 0, 0)),
    ("红色", (255, 0, 0)), ("深红色", (180, 0, 0)),
    ("黄色", (255, 255, 0)), ("金黄色", (255, 200, 0)),
    ("绿色", (0, 255, 0)), ("蓝色", (0, 0, 255)),
    ("青色", (0, 255, 255)), ("品红色", (255, 0, 255)),
    ("橙色", (255, 150, 0)), ("紫色", (150, 0, 255)),
    ("粉色", (255, 150, 200)), ("灰色", (128, 128, 128)),
    ("深灰色", (60, 60, 60)), ("浅灰色", (200, 200, 200)),
]


def _closest_color_name(rgb: tuple) -> str:
    best = min(_CN_COLORS, key=lambda x: _color_distance(rgb, x[1]))
    return best[0]


def _build_visual_desc(fill, out_on, out_c, sh_on, sh_c, sh_dx, sh_dy,
                       grad_on, glow_on, bg_on, bg_c) -> str:
    parts = [f"{_closest_color_name(fill)}填充文字"]
    if out_on:
        parts.append(f"，带{_closest_color_name(out_c)}描边")
    if sh_on:
        direction = "右下" if sh_dx > 0 and sh_dy > 0 else ("左下" if sh_dx < 0 and sh_dy > 0 else ("右上" if sh_dx > 0 else "左上"))
        parts.append(f"，{direction}{_closest_color_name(sh_c)}阴影")
    if grad_on:
        parts.append("，渐变色")
    if glow_on:
        parts.append("，发光效果")
    if bg_on:
        parts.append(f"，{_closest_color_name(bg_c)}底色框")
    return "".join(parts)


def _build_prompt(fill, out_on, out_c, out_w,
                  sh_on, sh_c, sh_dx, sh_dy,
                  grad_on, grad_s, grad_e,
                  glow_on, bg_on) -> str:
    parts = [f"文字颜色为{_rgb_to_hex(*fill)}（{_closest_color_name(fill)}）"]
    if out_on:
        parts.append(f"，描边颜色{_rgb_to_hex(*out_c)}，描边宽度约{out_w}px")
    if sh_on:
        parts.append(f"，阴影颜色{_rgb_to_hex(*sh_c)}，偏移({sh_dx},{sh_dy})")
    if grad_on:
        parts.append(f"，渐变从{_rgb_to_hex(*grad_s)}到{_rgb_to_hex(*grad_e)}")
    if glow_on:
        parts.append("，带发光效果")
    if bg_on:
        parts.append("，有底色框")
    return "".join(parts)


# ---------------------------------------------------------------------------
# default / file helpers
# ---------------------------------------------------------------------------

def _default_style(style_id: str, source_image: str,
                   rx: int, ry: int, rw: int, rh: int) -> dict:
    return {
        "style_id": style_id,
        "style_name": "用户框选花字样式",
        "source_image": source_image,
        "cropped_image": "",
        "selected_region": {"x": rx, "y": ry, "width": rw, "height": rh},
        "style_type": "custom_flower_text",
        "colors": {"fill_color": "#FFFFFF", "outline_color": "", "shadow_color": "", "background_color": ""},
        "effects": {"has_outline": False, "outline_width": 0, "has_shadow": False, "shadow_offset": [0, 0], "shadow_blur": 0, "has_gradient": False, "has_glow": False, "has_texture": False},
        "style_features": {"keywords": [], "complexity": "simple", "decoration_level": "minimal", "visual_description": "未知样式"},
        "render_config": {"fill": {"color": "#FFFFFF"}, "outline": None, "shadow": None, "effects": {"gradient": None, "glow": None, "texture": None}},
        "prompt": "未识别到文字样式",
    }


def generate_style_id(custom_styles_dir: str) -> str:
    """Generate a unique style_id based on existing files in the directory."""
    os.makedirs(custom_styles_dir, exist_ok=True)
    existing = [f for f in os.listdir(custom_styles_dir) if f.endswith(".json")]
    idx = len(existing) + 1
    while True:
        sid = f"custom_style_{idx:03d}"
        if not os.path.isfile(os.path.join(custom_styles_dir, f"{sid}.json")):
            return sid
        idx += 1


def save_style_json(style_dict: dict, custom_styles_dir: str) -> str:
    """Save a style dict as an independent JSON file. Returns the file path."""
    os.makedirs(custom_styles_dir, exist_ok=True)
    sid = style_dict.get("style_id", generate_style_id(custom_styles_dir))
    filepath = os.path.join(custom_styles_dir, f"{sid}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(style_dict, f, ensure_ascii=False, indent=2)
    return filepath


def load_style_json(filepath: str) -> dict | None:
    """Load an independent style JSON file."""
    if not os.path.isfile(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_all_styles(custom_styles_dir: str) -> list[dict]:
    """Load all style JSON files from a directory."""
    os.makedirs(custom_styles_dir, exist_ok=True)
    styles: list[dict] = []
    for f in sorted(os.listdir(custom_styles_dir)):
        if f.endswith(".json"):
            data = load_style_json(os.path.join(custom_styles_dir, f))
            if data:
                styles.append(data)
    return styles


def style_to_text_layer(style_dict: dict) -> dict:
    """Convert a style JSON dict to TextLayerModel-compatible fields for apply_template."""
    colors = style_dict.get("colors", {})
    effects = style_dict.get("effects", {})
    render = style_dict.get("render_config", {})
    rend_effects = render.get("effects", {}) or {}

    result: dict = {
        "font_family": "Microsoft YaHei",
        "font_size": 48,
        "fill_color": colors.get("fill_color", "#FFFFFF"),
        "stroke_enabled": effects.get("has_outline", False),
        "stroke_color": colors.get("outline_color", "#000000"),
        "stroke_width": effects.get("outline_width", 3),
        "shadow_enabled": effects.get("has_shadow", False),
        "shadow_color": colors.get("shadow_color", "#000000"),
        "shadow_offset_x": effects.get("shadow_offset", [3, 3])[0],
        "shadow_offset_y": effects.get("shadow_offset", [3, 3])[1],
        "shadow_blur": effects.get("shadow_blur", 4),
        "gradient_enabled": effects.get("has_gradient", False),
        "gradient_start": (rend_effects.get("gradient") or {}).get("start", "#FFFFFF"),
        "gradient_end": (rend_effects.get("gradient") or {}).get("end", "#FFD700"),
        "background_enabled": bool(colors.get("background_color", "")),
        "background_color": colors.get("background_color", "#000000"),
        "opacity": 1.0,
    }
    return result
