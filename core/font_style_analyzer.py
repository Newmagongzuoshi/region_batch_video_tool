"""Analyze a selected image region to produce an independent flower-text style JSON.

OpenCV-based pipeline:
  1. Generate text mask via HSV saturation + morphology (handles white-fill)
  2. Cluster foreground colors in LAB space with KMeans (perceptual accuracy)
  3. Classify layers via distanceTransform (spatial: outer→inner→fill→shadow)
  4. Estimate stroke width via skeletonize + distanceTransform on fill mask
  5. Output JSON + debug visualizations

This module does NOT:
- Match against any existing template library
- Recognize font names
- OCR text content
- Call any online API
"""

from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any

import cv2
import numpy as np
from PIL import Image
from sklearn.cluster import MiniBatchKMeans


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02X}{g:02X}{b:02X}"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _color_distance(c1: tuple, c2: tuple) -> float:
    return float(np.sqrt((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2))


def _luminance(rgb: tuple) -> float:
    return rgb[0] * 0.299 + rgb[1] * 0.587 + rgb[2] * 0.114


def _is_dark(rgb: tuple) -> bool:
    return _luminance(rgb) < 128


def _hue(rgb: tuple) -> float:
    """Return hue angle 0-360 for an RGB color."""
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


def _saturation_rgb(rgb: tuple) -> float:
    r, g, b = [c / 255.0 for c in rgb]
    mx = max(r, g, b)
    if mx == 0:
        return 0.0
    return (mx - min(r, g, b)) / mx


# ---------------------------------------------------------------------------
# 0. Auto-detect text region
# ---------------------------------------------------------------------------

def _detect_text_region(image: Image.Image, padding: int = 10) -> tuple[int, int, int, int] | None:
    """Auto-detect the text bounding box in a full-canvas image.

    Uses row/column variance to find where text pixels differ from uniform bg.
    """
    arr = np.array(image.convert("RGB"))
    h, w = arr.shape[:2]

    # Find rows with significant color variation (text vs bg)
    non_uniform_rows = []
    for ri in range(h):
        unique = len(np.unique(arr[ri].reshape(-1, 3), axis=0))
        if unique > 10:
            non_uniform_rows.append(ri)

    non_uniform_cols = []
    for ci in range(w):
        unique = len(np.unique(arr[:, ci].reshape(-1, 3), axis=0))
        if unique > 10:
            non_uniform_cols.append(ci)

    if len(non_uniform_rows) < 4 or len(non_uniform_cols) < 4:
        return None

    ct = non_uniform_rows[0]
    cb = non_uniform_rows[-1]
    cl = non_uniform_cols[0]
    cr = non_uniform_cols[-1]

    return (
        max(0, cl - padding),
        max(0, ct - padding),
        min(w, cr - cl + 2 * padding),
        min(h, cb - ct + 2 * padding),
    )


# ---------------------------------------------------------------------------
# 1. Mask generation — handles white-fill, multi-line, anti-aliasing
# ---------------------------------------------------------------------------

def _build_text_mask(bgr: np.ndarray, alpha: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Build a binary mask covering ALL text pixels including white fill.

    Strategy:
      (a) Alpha mask (for GIFs with transparency) — best signal
      (b) Saturation mask — picks up colored strokes/shadows
      (c) Gradient magnitude mask — finds edges between text and bg
      (d) Combine, then morphology close + dilate
      (e) Contour fill + edge-aware bg removal

    Returns (final_mask, sat_mask_for_debug).
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]

    # (a) Alpha mask: only use if image has actual transparency (GIFs).
    # For solid PNGs (alpha=255 everywhere), skip to avoid all-ones mask.
    if alpha is not None and np.any(alpha < 240):
        _, alpha_mask = cv2.threshold(alpha, 25, 255, cv2.THRESH_BINARY)
    else:
        alpha_mask = np.zeros_like(s, dtype=np.uint8)

    # (b) Saturation mask
    _, sat_mask = cv2.threshold(s, 25, 255, cv2.THRESH_BINARY)

    # (c) Gradient magnitude mask
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    grad_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    grad_mag = np.sqrt(grad_x ** 2 + grad_y ** 2)
    grad_mag = np.clip(grad_mag, 0, 255).astype(np.uint8)
    _, grad_mask = cv2.threshold(grad_mag, 8, 255, cv2.THRESH_BINARY)

    # (d) Combine all three
    combined = cv2.bitwise_or(alpha_mask, sat_mask)
    combined = cv2.bitwise_or(combined, grad_mask)

    # (d) Morphology: close gaps, then dilate to fill white interiors
    kernel_large = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    kernel_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel_large, iterations=1)
    combined = cv2.dilate(combined, kernel_small, iterations=2)
    combined = cv2.erode(combined, kernel_small, iterations=1)

    # (e) Contour fill
    contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(combined)
    for cnt in contours:
        cv2.drawContours(filled, [cnt], -1, 255, cv2.FILLED)

    # (f) Remove background-leak only near mask edges (preserves white fill inside strokes)
    h, w = bgr.shape[:2]
    corners = [bgr[0, 0], bgr[0, w - 1], bgr[h - 1, 0], bgr[h - 1, w - 1]]
    bg_color = np.median(corners, axis=0).astype(np.float32)
    bg_dist = np.sqrt(np.sum((bgr.astype(np.float32) - bg_color) ** 2, axis=2))
    bg_proximity = (bg_dist < 18).astype(np.uint8)

    # Only remove bg-proximate pixels that are near the mask boundary
    dist_from_edge = cv2.distanceTransform(filled, cv2.DIST_L2, 5)
    edge_region = (dist_from_edge < 4).astype(np.uint8)
    bg_leak = cv2.bitwise_and(bg_proximity, edge_region).astype(np.uint8) * 255

    filled = cv2.bitwise_and(filled, cv2.bitwise_not(bg_leak))
    # Re-dilate slightly to close any gaps
    filled = cv2.dilate(filled, kernel_small, iterations=1)

    return filled, sat_mask


# ---------------------------------------------------------------------------
# 2. Color clustering in LAB space
# ---------------------------------------------------------------------------

def _cluster_colors_lab(
    bgr: np.ndarray, mask: np.ndarray, n_clusters: int = 5
) -> tuple[list[tuple[int, int, int]], list[float], np.ndarray]:
    """KMeans cluster foreground colors in LAB space.

    Returns:
      centroids_rgb: list of (R,G,B) centroid colors
      ratios: list of pixel-count ratios per cluster
      labels_map: 2D label image (same size as input), -1 = background
    """
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    fg_pixels = lab[mask > 0]  # (N, 3)
    if len(fg_pixels) < n_clusters:
        n_clusters = max(2, len(fg_pixels))

    # Normalize LAB for better clustering
    lab_mean = fg_pixels.mean(axis=0)
    lab_std = fg_pixels.std(axis=0) + 1e-6
    fg_norm = (fg_pixels - lab_mean) / lab_std

    kmeans = MiniBatchKMeans(n_clusters=n_clusters, random_state=42, n_init=10, batch_size=min(4096, len(fg_norm)))
    labels_1d = kmeans.fit_predict(fg_norm)
    centroids_norm = kmeans.cluster_centers_
    # Denormalize centroids
    centroids_lab = centroids_norm * lab_std + lab_mean
    centroids_lab = np.clip(centroids_lab, 0, 255).astype(np.uint8)

    # Convert centroids to RGB
    centroids_rgb: list[tuple[int, int, int]] = []
    for cl in centroids_lab:
        lab_pixel = np.array([[cl]], dtype=np.uint8)
        bgr_pixel = cv2.cvtColor(lab_pixel, cv2.COLOR_LAB2BGR)
        r, g, b = int(bgr_pixel[0, 0, 2]), int(bgr_pixel[0, 0, 1]), int(bgr_pixel[0, 0, 0])
        centroids_rgb.append((r, g, b))

    # Ratios
    total = len(labels_1d)
    ratios: list[float] = []
    for i in range(n_clusters):
        ratios.append(float(np.sum(labels_1d == i)) / total)

    # Build label map
    labels_map = np.full(bgr.shape[:2], -1, dtype=np.int32)
    ys, xs = np.where(mask > 0)
    for idx in range(len(ys)):
        labels_map[ys[idx], xs[idx]] = int(labels_1d[idx])

    return centroids_rgb, ratios, labels_map


# ---------------------------------------------------------------------------
# 3. Spatial layer classification via distance transform
# ---------------------------------------------------------------------------

def _classify_layers(
    mask: np.ndarray,
    labels_map: np.ndarray,
    centroids_rgb: list[tuple[int, int, int]],
    ratios: list[float],
) -> dict:
    """Use distanceTransform to classify each color cluster by spatial position.

    Returns dict with keys: fill_rgb, outer_stroke_rgb, inner_stroke_rgb,
      shadow_rgb, shadow_offset, stroke_width_estimate, confidence
    """
    # Distance transform: distance from each pixel to nearest background
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    max_dist = dist.max()
    if max_dist < 2:
        return _empty_classification(centroids_rgb[0] if centroids_rgb else (255, 255, 255))

    # For each cluster, compute mean distance from edge
    cluster_stats: list[dict[str, Any]] = []
    for ci in range(len(centroids_rgb)):
        cl_mask = (labels_map == ci)
        cl_pixels = np.sum(cl_mask)
        if cl_pixels < 10:
            continue
        cl_distances = dist[cl_mask]
        stats = {
            "cluster_id": ci,
            "centroid_rgb": centroids_rgb[ci],
            "ratio": ratios[ci],
            "pixels": int(cl_pixels),
            "mean_dist": float(np.mean(cl_distances)),
            "median_dist": float(np.median(cl_distances)),
            "p10_dist": float(np.percentile(cl_distances, 10)),
            "p90_dist": float(np.percentile(cl_distances, 90)),
            "luminance": _luminance(centroids_rgb[ci]),
        }
        cluster_stats.append(stats)

    if len(cluster_stats) < 2:
        s = cluster_stats[0] if cluster_stats else {"centroid_rgb": (255, 255, 255), "median_dist": 0}
        return {
            "fill_rgb": s["centroid_rgb"],
            "outer_stroke_rgb": None,
            "inner_stroke_rgb": None,
            "shadow_rgb": None,
            "shadow_offset": [0, 0],
            "stroke_width_estimate": 0,
            "confidence": 0.3,
            "cluster_stats": cluster_stats,
        }

    # Sort by median distance from edge (outer → inner)
    by_dist = sorted(cluster_stats, key=lambda x: x["median_dist"])

    # Fill = deepest among top-3 by size, with saturation bonus.
    # Prevents white bg-leak cluster from being picked over real colored fill.
    by_size = sorted(cluster_stats, key=lambda x: x["ratio"], reverse=True)
    top_candidates = by_size[:min(3, len(by_size))]
    best_fill = None
    best_score = -1.0
    for s in top_candidates:
        sat = _saturation_rgb(s["centroid_rgb"])
        score = s["median_dist"] * (0.3 + 0.7 * sat)  # depth weighted by saturation
        if score > best_score:
            best_score = score
            best_fill = s
    fill_stats = best_fill if best_fill else top_candidates[0]
    fill_rgb: tuple = fill_stats["centroid_rgb"]
    fill_lum = _luminance(fill_rgb)

    outer_stroke_rgb: tuple | None = None
    inner_stroke_rgb: tuple | None = None
    shadow_rgb: tuple | None = None
    shadow_offset = [0, 0]
    stroke_width_estimate = 0
    confidence = 0.5

    # Outer stroke = shallowest cluster distinct from fill, with real color
    for s in by_dist:
        if _color_distance(s["centroid_rgb"], fill_rgb) < 20:
            continue
        if s["ratio"] < 0.02:
            continue
        # Skip near-white/unsaturated — probably bg leakage, not a stroke
        if _saturation_rgb(s["centroid_rgb"]) < 0.08:
            continue
        outer_stroke_rgb = s["centroid_rgb"]
        stroke_width_estimate = max(1, int(s["p90_dist"]))
        confidence = min(0.85, confidence + 0.2)
        break

    # Inner stroke = between outer and fill, distinct color from both
    if outer_stroke_rgb and len(cluster_stats) >= 3:
        outer_d = next((s["median_dist"] for s in by_dist if s["centroid_rgb"] == outer_stroke_rgb), 0)
        fill_d = fill_stats["median_dist"]
        for s in by_dist:
            if _color_distance(s["centroid_rgb"], fill_rgb) < 15:
                continue
            if _color_distance(s["centroid_rgb"], outer_stroke_rgb) < 15:
                continue
            if _saturation_rgb(s["centroid_rgb"]) < 0.05:
                continue
            if outer_d < s["median_dist"] < fill_d + 1 and s["ratio"] > 0.02:
                inner_stroke_rgb = s["centroid_rgb"]
                confidence = min(0.95, confidence + 0.2)
                break

    # Shadow = dark cluster with significant spatial offset from fill
    for s in by_dist:
        if not _is_dark(s["centroid_rgb"]):
            continue
        if _color_distance(s["centroid_rgb"], fill_rgb) < 25:
            continue
        if s["ratio"] < 0.01:
            continue
        fill_mask_arr = (labels_map == fill_stats["cluster_id"])
        dark_mask = (labels_map == s["cluster_id"])
        fy, fx = np.where(fill_mask_arr)
        dy, dx = np.where(dark_mask)
        if len(dy) > 3 and len(fy) > 3:
            sdx = int(np.mean(dx) - np.mean(fx))
            sdy = int(np.mean(dy) - np.mean(fy))
            if abs(sdx) > 5 or abs(sdy) > 3:
                shadow_rgb = s["centroid_rgb"]
                shadow_offset = [sdx, sdy]
                confidence = min(0.9, confidence + 0.1)
                break

    return {
        "fill_rgb": fill_rgb,
        "outer_stroke_rgb": outer_stroke_rgb,
        "inner_stroke_rgb": inner_stroke_rgb,
        "shadow_rgb": shadow_rgb,
        "shadow_offset": shadow_offset,
        "stroke_width_estimate": stroke_width_estimate,
        "confidence": confidence,
        "cluster_stats": cluster_stats,
        "max_dist": float(max_dist),
    }


def _empty_classification(fill_rgb: tuple) -> dict:
    return {
        "fill_rgb": fill_rgb,
        "outer_stroke_rgb": None,
        "inner_stroke_rgb": None,
        "shadow_rgb": None,
        "shadow_offset": [0, 0],
        "stroke_width_estimate": 0,
        "confidence": 0.0,
        "cluster_stats": [],
        "max_dist": 0.0,
    }


# ---------------------------------------------------------------------------
# 4. Stroke width estimation via skeletonize
# ---------------------------------------------------------------------------

def _estimate_stroke_width(mask: np.ndarray, fill_label: int | None,
                           labels_map: np.ndarray) -> float:
    """Estimate visual stroke width using skeletonization + distance transform."""
    try:
        from skimage.morphology import skeletonize
    except ImportError:
        # Fallback: use distance transform median
        dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
        vals = dist[mask > 0]
        if len(vals) == 0:
            return 0
        return float(np.median(vals)) * 2.0

    if fill_label is not None:
        fill_mask = (labels_map == fill_label).astype(np.uint8) * 255
        if np.sum(fill_mask) < 50:
            fill_mask = mask.copy()
    else:
        fill_mask = mask.copy()

    # Skeletonize
    skel = skeletonize(fill_mask > 0)
    if not np.any(skel):
        return 0

    # Distance transform on fill mask
    dist = cv2.distanceTransform(fill_mask, cv2.DIST_L2, 5)
    radii = dist[skel]
    if len(radii) == 0:
        return 0

    # Median radius × 2 = stroke width
    return float(np.median(radii)) * 2.0


# ---------------------------------------------------------------------------
# 5. Debug visualization
# ---------------------------------------------------------------------------

def _make_debug_images(
    bgr: np.ndarray,
    mask: np.ndarray,
    sat_mask: np.ndarray,
    labels_map: np.ndarray,
    centroids_rgb: list[tuple[int, int, int]],
    ratios: list[float],
    classification: dict,
    output_dir: str,
    base_name: str,
) -> dict[str, str]:
    """Generate debug images and return paths."""
    os.makedirs(output_dir, exist_ok=True)
    h, w = bgr.shape[:2]
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    # --- debug_mask.png ---
    mask_viz = np.zeros((h, w * 3, 3), dtype=np.uint8)
    mask_viz[:, :w] = rgb
    mask_viz[:, w:2 * w, 0] = sat_mask  # saturation mask in red channel
    mask_viz[:, w:2 * w, 1] = 0
    mask_viz[:, w:2 * w, 2] = 0
    mask_viz[:, 2 * w:, 1] = mask  # final mask in green channel
    # Draw bbox on original
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        all_pts = np.vstack(contours)
        x, y, bw, bh = cv2.boundingRect(all_pts)
        cv2.rectangle(mask_viz, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
    mask_path = os.path.join(output_dir, f"{base_name}_debug_mask.png")
    cv2.imwrite(mask_path, cv2.cvtColor(mask_viz, cv2.COLOR_RGB2BGR))

    # --- debug_clusters.png ---
    n_clusters = len(centroids_rgb)
    cols = min(4, n_clusters)
    rows = (n_clusters + cols - 1) // cols
    cell_h, cell_w = h, w
    cluster_viz = np.zeros((rows * cell_h, cols * cell_w, 3), dtype=np.uint8)
    for ci in range(n_clusters):
        r_idx = ci // cols
        c_idx = ci % cols
        y0, y1 = r_idx * cell_h, (r_idx + 1) * cell_h
        x0, x1 = c_idx * cell_w, (c_idx + 1) * cell_w
        # Show only this cluster's pixels
        cl_mask = (labels_map == ci)
        cluster_viz[y0:y1, x0:x1] = rgb * np.expand_dims(cl_mask, 2)
        # Label
        hex_c = _rgb_to_hex(*centroids_rgb[ci])
        cv2.putText(cluster_viz, f"C{ci} {hex_c} {ratios[ci]:.1%}",
                    (x0 + 5, y0 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
    cluster_path = os.path.join(output_dir, f"{base_name}_debug_clusters.png")
    cv2.imwrite(cluster_path, cv2.cvtColor(cluster_viz, cv2.COLOR_RGB2BGR))

    # --- debug_layers.png ---
    layer_viz = rgb.copy()
    overlay = np.zeros_like(layer_viz)
    stats = classification.get("cluster_stats", [])
    if stats:
        for s in stats:
            ci = s["cluster_id"]
            cl_mask = (labels_map == ci)
            centroid = s["centroid_rgb"]
            if centroid == classification.get("fill_rgb"):
                color = (0, 0, 255)  # Red = fill
            elif centroid == classification.get("outer_stroke_rgb"):
                color = (255, 0, 0)  # Blue = outer stroke
            elif centroid == classification.get("inner_stroke_rgb"):
                color = (0, 255, 0)  # Green = inner stroke / glow
            elif centroid == classification.get("shadow_rgb"):
                color = (0, 0, 0)  # Black = shadow
            else:
                color = (128, 128, 128)  # Gray = other
            overlay[cl_mask] = color
    layer_viz = cv2.addWeighted(layer_viz, 0.5, overlay, 0.5, 0)
    # Annotate
    y_off = 20
    for label, key, c in [
        ("Fill", "fill_rgb", (0, 0, 255)),
        ("OuterStroke", "outer_stroke_rgb", (255, 0, 0)),
        ("InnerStroke", "inner_stroke_rgb", (0, 255, 0)),
        ("Shadow", "shadow_rgb", (0, 0, 0)),
    ]:
        val = classification.get(key)
        if val:
            cv2.putText(layer_viz, f"{label}: {_rgb_to_hex(*val)}",
                        (5, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 1)
            y_off += 18
    layer_path = os.path.join(output_dir, f"{base_name}_debug_layers.png")
    cv2.imwrite(layer_path, cv2.cvtColor(layer_viz, cv2.COLOR_RGB2BGR))

    # --- debug_summary.png ---
    summary = np.zeros((max(h, 400), w * 2, 3), dtype=np.uint8)
    summary[:h, :w] = rgb
    # Right side: summary text on dark bg
    summary[:, w:] = (30, 30, 30)
    y_off = 25
    lines = [
        f"Fill: {_rgb_to_hex(*classification['fill_rgb'])}",
        f"OuterStroke: {_rgb_to_hex(*classification['outer_stroke_rgb']) if classification['outer_stroke_rgb'] else 'None'}",
        f"InnerStroke: {_rgb_to_hex(*classification['inner_stroke_rgb']) if classification['inner_stroke_rgb'] else 'None'}",
        f"Shadow: {_rgb_to_hex(*classification['shadow_rgb']) if classification['shadow_rgb'] else 'None'}",
        f"StrokeWidth: {classification['stroke_width_estimate']:.1f}px",
        f"Confidence: {classification['confidence']:.1%}",
        f"Clusters: {len(centroids_rgb)}",
    ]
    for line in lines:
        cv2.putText(summary, line, (w + 10, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 200), 1)
        y_off += 20
    summary_path = os.path.join(output_dir, f"{base_name}_debug_summary.png")
    cv2.imwrite(summary_path, cv2.cvtColor(summary, cv2.COLOR_RGB2BGR))

    return {
        "debug_mask": mask_path,
        "debug_clusters": cluster_path,
        "debug_layers": layer_path,
        "debug_summary": summary_path,
    }


# ---------------------------------------------------------------------------
# main analyzer
# ---------------------------------------------------------------------------

def quick_sample_colors(image: Image.Image) -> dict:
    """Fast extraction of just fill + stroke colors from a GIF frame.

    Returns {'fill': '#XXXXXX', 'stroke': '#XXXXXX', 'text_top_y': int}
    """
    import cv2
    import numpy as np

    if image.mode == "RGBA":
        alpha = np.array(image.split()[3])
        rgb = Image.new("RGB", image.size, (255, 255, 255))
        rgb.paste(image, mask=image.split()[3])
    else:
        alpha = None
        rgb = image.convert("RGB")

    arr = np.array(rgb)
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    h, w = arr.shape[:2]

    # Auto-detect text region
    nr = [ri for ri in range(h) if len(np.unique(arr[ri].reshape(-1, 3), axis=0)) > 10]
    nc = [ci for ci in range(w) if len(np.unique(arr[:, ci].reshape(-1, 3), axis=0)) > 10]

    if len(nr) < 4 or len(nc) < 4:
        return {'fill': '#FFFFFF', 'stroke': '#000000', 'text_top_y': 0}

    ct, cb, cl, cr = nr[0], nr[-1], nc[0], nc[-1]
    rx, ry = max(0, cl - 5), max(0, ct - 5)
    rw, rh = min(w - rx, cr - cl + 11), min(h - ry, cb - ct + 11)
    crop = bgr[ry:ry + rh, rx:rx + rw]
    alpha_crop = alpha[ry:ry + rh, rx:rx + rw] if alpha is not None else None

    # Simple mask: alpha + saturation
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    _, sat_mask = cv2.threshold(hsv[:, :, 1], 25, 255, cv2.THRESH_BINARY)
    if alpha_crop is not None and np.any(alpha_crop < 240):
        _, am = cv2.threshold(alpha_crop, 30, 255, cv2.THRESH_BINARY)
        mask = cv2.bitwise_or(sat_mask, am)
    else:
        mask = sat_mask
    ks = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.dilate(mask, ks, iterations=1)

    # Get non-white pixels in mask
    ys, xs = np.where(mask > 0)
    if len(ys) < 50:
        return {'fill': '#FFFFFF', 'stroke': '#000000', 'text_top_y': ct}

    colors = []
    depths = []
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    max_d = dist.max()

    for y, x in zip(ys, xs):
        c = tuple(int(v) for v in crop[y, x])
        if not (c[0] > 240 and c[1] > 240 and c[2] > 240):
            colors.append(c)
            depths.append(dist[y, x])

    if len(colors) < 20:
        return {'fill': '#FFFFFF', 'stroke': '#000000', 'text_top_y': ct}

    # Quantize to find dominant colors
    from collections import Counter
    quant = Counter((c[0] // 32 * 32, c[1] // 32 * 32, c[2] // 32 * 32) for c in colors)
    top_bins = quant.most_common(8)

    # Group by depth (shallow vs deep)
    shallow_colors = []
    deep_colors = []
    for q, _ in top_bins:
        # Find median depth for this bin
        bin_depths = [depths[i] for i, c in enumerate(colors)
                      if (c[0] // 32 * 32, c[1] // 32 * 32, c[2] // 32 * 32) == q]
        if not bin_depths:
            continue
        md = float(np.median(bin_depths))
        rgb_c = (q[2], q[1], q[0])
        if md < max_d * 0.3:
            shallow_colors.append((rgb_c, md, len(bin_depths)))
        else:
            deep_colors.append((rgb_c, md, len(bin_depths)))

    # Fill = largest deep saturated color
    fill_rgb = (255, 255, 255)
    for c, _, n in sorted(deep_colors, key=lambda x: -x[2]):
        sat = (max(c) - min(c)) / max(1, max(c))
        if sat > 0.10:
            fill_rgb = c
            break

    # Stroke = shallow color most DISTINCT from fill (largest color distance)
    stroke_rgb = (0, 0, 0)
    best_dist = 0
    for c, _, n in shallow_colors:
        sat = (max(c) - min(c)) / max(1, max(c))
        if sat < 0.08:
            continue
        dist_to_fill = _color_distance(c, fill_rgb)
        if dist_to_fill > best_dist:
            best_dist = dist_to_fill
            stroke_rgb = c
    # Fallback: if no distinct shallow color, use darkest shallow
    if best_dist < 25 and deep_colors:
        stroke_rgb = fill_rgb  # no distinct stroke, use fill color

    return {
        'fill': f'#{fill_rgb[0]:02X}{fill_rgb[1]:02X}{fill_rgb[2]:02X}',
        'stroke': f'#{stroke_rgb[0]:02X}{stroke_rgb[1]:02X}{stroke_rgb[2]:02X}',
        'text_top_y': ct,
    }


def analyze_text_style(
    image: Image.Image,
    region: tuple[int, int, int, int] | None = None,
    style_id: str = "",
    source_image: str = "",
    debug_dir: str = "",
) -> dict:
    """Analyze a text region and produce a flower-text style JSON.

    Args:
        image: PIL Image (RGBA or RGB)
        region: (x, y, w, h) crop region within image
        style_id: identifier for this style
        source_image: path to source image (for metadata)
        debug_dir: if non-empty, write debug PNGs to this directory

    Returns a dict matching the custom_styles JSON schema.
    """
    try:
        return _analyze_impl(image, region, style_id, source_image, debug_dir)
    except Exception as e:
        # Single-image failure must not crash batch processing
        import traceback
        traceback.print_exc()
        rx = region[0] if region else 0
        ry = region[1] if region else 0
        rw = region[2] if region else image.width
        rh = region[3] if region else image.height
        result = _default_style(style_id, source_image, rx, ry, rw, rh)
        result["error"] = str(e)
        return result


def _analyze_impl(
    image: Image.Image,
    region: tuple[int, int, int, int] | None,
    style_id: str,
    source_image: str,
    debug_dir: str,
) -> dict:
    # ---- Crop ----
    if region:
        rx, ry, rw, rh = region
        crop = image.crop((rx, ry, rx + rw, ry + rh))
    else:
        # Auto-detect text region from full image
        region = _detect_text_region(image)
        if region:
            rx, ry, rw, rh = region
            crop = image.crop((rx, ry, rx + rw, ry + rh))
        else:
            crop = image.copy()
            rx, ry, rw, rh = 0, 0, crop.width, crop.height

    if crop.width < 4 or crop.height < 4:
        return _default_style(style_id, source_image, rx, ry, rw, rh)

    # Convert to BGR (OpenCV), preserve alpha for mask generation
    alpha_channel = None
    if crop.mode == "RGBA":
        alpha_channel = np.array(crop.split()[3])
        crop_rgb = Image.new("RGB", crop.size, (255, 255, 255))
        crop_rgb.paste(crop, mask=crop.split()[3])
    else:
        crop_rgb = crop.convert("RGB")

    bgr = cv2.cvtColor(np.array(crop_rgb), cv2.COLOR_RGB2BGR)

    # ---- Step 1: Build text mask (uses alpha when available) ----
    mask, sat_mask = _build_text_mask(bgr, alpha_channel)
    if np.sum(mask) < 50:
        return _default_style(style_id, source_image, rx, ry, rw, rh)

    # ---- Step 2: Quantize + spatial classification ----
    # Quantize foreground colors into ~10 bins/channel, count per bin,
    # then classify by median depth from mask edge.  Much more stable
    # than KMeans or ring-based approaches.
    dist_img = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    max_d = dist_img.max() if dist_img.max() > 0 else 1

    fg_pixels = []
    ys, xs = np.where(mask > 0)
    for y, x in zip(ys, xs):
        c = tuple(int(v) for v in bgr[y, x])
        d = dist_img[y, x]
        fg_pixels.append((c, d))

    total_fg = len(fg_pixels)
    if total_fg < 100:
        return _default_style(style_id, source_image, rx, ry, rw, rh)

    Q = 40
    quantized: dict[tuple, dict] = {}
    for (c, d) in fg_pixels:
        q = (c[0] // Q * Q, c[1] // Q * Q, c[2] // Q * Q)
        if q not in quantized:
            quantized[q] = {'count': 0, 'depths': [], 'raw': []}
        quantized[q]['count'] += 1
        quantized[q]['depths'].append(d)
        quantized[q]['raw'].append(c)

    filtered = {}
    for q, data in quantized.items():
        is_nw = q[0] > 220 and q[1] > 220 and q[2] > 220
        md = float(np.median(data['depths']))
        if is_nw and md < max_d * 0.35:
            continue
        if data['count'] < total_fg * 0.008:
            continue
        filtered[q] = data

    if len(filtered) < 2:
        return _default_style(style_id, source_image, rx, ry, rw, rh)

    top8 = sorted(filtered.items(), key=lambda x: -x[1]['count'])[:8]
    candidates = []
    for q, data in top8:
        arr = np.array(data['raw'])
        rep = tuple(int(x) for x in np.median(arr, axis=0))
        md = float(np.median(data['depths']))
        ratio = data['count'] / total_fg
        sat_val = _saturation_rgb((rep[2], rep[1], rep[0]))
        candidates.append({
            'color_bgr': rep, 'depth': md, 'ratio': ratio, 'sat': sat_val,
            'hex': _rgb_to_hex(rep[2], rep[1], rep[0]),
        })

    candidates.sort(key=lambda x: x['depth'])

    # ---- Step 3: Classify layers by depth ----
    # Fill: combined score = ratio × saturation × depth/max_d.
    # Large + saturated + deep = most likely the true fill.
    for c in candidates:
        c['fill_score'] = c['ratio'] * c['sat'] * (0.3 + 0.7 * c['depth'] / max(1, max_d))
    fill_cand = max(candidates, key=lambda c: c['fill_score'])

    fill_rgb_bgr = fill_cand['color_bgr']
    fill_rgb = (fill_rgb_bgr[2], fill_rgb_bgr[1], fill_rgb_bgr[0])

    outer_cand = candidates[0]
    if outer_cand['sat'] < 0.04 and len(candidates) >= 2:
        outer_cand = candidates[1]

    outer_stroke_rgb = None
    inner_stroke_rgb = None
    outline_type = "dark"
    outer_width = 0

    if outer_cand is not fill_cand and outer_cand['depth'] < fill_cand['depth'] * 0.7:
        outer_bgr = outer_cand['color_bgr']
        outer_stroke_rgb = (outer_bgr[2], outer_bgr[1], outer_bgr[0])
        fl = 0.299 * fill_rgb[0] + 0.587 * fill_rgb[1] + 0.114 * fill_rgb[2]
        ol = 0.299 * outer_stroke_rgb[0] + 0.587 * outer_stroke_rgb[1] + 0.114 * outer_stroke_rgb[2]
        outline_type = "glow" if ol > fl + 10 else "dark"

        # Stroke width: walk rings from edge inward, find where color
        # transitions from outer→fill.  Filter near-white from each ring.
        outer_width = 1
        max_d_int = int(np.ceil(max_d))
        for d in range(1, max_d_int + 1):
            ring_mask = (dist_img >= d - 0.5) & (dist_img < d + 0.5) & (mask > 0)
            if np.sum(ring_mask) < 5:
                continue
            ring_pixels = bgr[ring_mask]
            ring_f = [p for p in ring_pixels
                      if not (p[0] > 235 and p[1] > 235 and p[2] > 235)]
            if len(ring_f) < 3:
                ring_f = ring_pixels
            ring_quant = [(int(p[0])//20*20, int(p[1])//20*20, int(p[2])//20*20) for p in ring_f]
            ring_mode = Counter(ring_quant).most_common(1)[0][0]
            ring_rgb = (ring_mode[2], ring_mode[1], ring_mode[0])
            d_outer = _color_distance(ring_rgb, outer_stroke_rgb)
            d_fill = _color_distance(ring_rgb, fill_rgb)
            if d_outer < d_fill:
                outer_width = d
            else:
                break
        # Minimum 2px for any detected stroke (AA makes 1px unreliable)
        outer_width = max(2, outer_width)

    if outer_stroke_rgb and len(candidates) >= 3:
        for c in candidates[1:-1]:
            if c is fill_cand or c is outer_cand:
                continue
            c_rgb = (c['color_bgr'][2], c['color_bgr'][1], c['color_bgr'][0])
            cd_fill = _color_distance(c_rgb, fill_rgb)
            cd_outer = _color_distance(c_rgb, outer_stroke_rgb)
            if cd_fill > 20 and cd_outer > 20:
                inner_stroke_rgb = c_rgb
                outline_type = "double"
                break

    outline_enabled = outer_stroke_rgb is not None

    cluster_stats = []
    if outer_stroke_rgb:
        cluster_stats.append({"centroid_rgb": outer_stroke_rgb, "ratio": outer_cand['ratio'],
            "median_dist": outer_cand['depth'], "cluster_id": 1, "p90_dist": outer_width,
            "luminance": _luminance(outer_stroke_rgb)})
    if inner_stroke_rgb:
        cluster_stats.append({"centroid_rgb": inner_stroke_rgb, "ratio": 0.05,
            "median_dist": (outer_cand['depth'] + fill_cand['depth']) / 2,
            "cluster_id": 2, "p90_dist": 1, "luminance": _luminance(inner_stroke_rgb)})
    cluster_stats.append({"centroid_rgb": fill_rgb, "ratio": fill_cand['ratio'],
        "median_dist": fill_cand['depth'], "cluster_id": 0, "p90_dist": fill_cand['depth'],
        "luminance": _luminance(fill_rgb)})

    classification = {
        "fill_rgb": fill_rgb, "outer_stroke_rgb": outer_stroke_rgb,
        "inner_stroke_rgb": inner_stroke_rgb, "shadow_rgb": None,
        "shadow_offset": [0, 0], "stroke_width_estimate": outer_width,
        "confidence": 0.7, "cluster_stats": cluster_stats, "max_dist": float(max_d),
    }

    centroids_rgb = [fill_rgb]
    if outer_stroke_rgb: centroids_rgb.append(outer_stroke_rgb)
    if inner_stroke_rgb: centroids_rgb.append(inner_stroke_rgb)

    labels_map = np.full(bgr.shape[:2], -1, dtype=np.int32)
    if outer_stroke_rgb:
        labels_map[(dist_img < outer_cand['depth'] * 0.8) & (mask > 0)] = 1
    if inner_stroke_rgb:
        mid_d = (outer_cand['depth'] + fill_cand['depth']) / 2
        labels_map[(dist_img >= outer_cand['depth'] * 0.8) & (dist_img < mid_d) & (mask > 0)] = 2
    labels_map[(dist_img >= fill_cand['depth'] * 0.6) & (mask > 0)] = 0


    # ---- Step 4: Gradient detection on fill region ----
    gradient_enabled = False
    grad_start = fill_rgb
    grad_end = fill_rgb
    gradient_direction = "topToBottom"

    # Fill = labels_map == 0 (innermost ring region)
    fill_mask_arr = (labels_map == 0) & (mask > 0)
    ys, xs = np.where(fill_mask_arr)
    if len(ys) > 30:
        min_y, max_y = ys.min(), ys.max()
        min_x, max_x = xs.min(), xs.max()
        band_h = max(2, (max_y - min_y) // 6)
        band_w = max(2, (max_x - min_x) // 6)
        top_band = bgr[(np.arange(bgr.shape[0])[:, None] <= min_y + band_h) & fill_mask_arr]
        bot_band = bgr[(np.arange(bgr.shape[0])[:, None] >= max_y - band_h) & fill_mask_arr]
        if len(top_band) >= 5 and len(bot_band) >= 5:
            top_avg = tuple(int(x) for x in np.mean(top_band, axis=0)[::-1])
            bot_avg = tuple(int(x) for x in np.mean(bot_band, axis=0)[::-1])
            if _color_distance(top_avg, bot_avg) > 20:
                gradient_enabled = True
                grad_start = top_avg
                grad_end = bot_avg

    display_fill_rgb = fill_rgb

    # ---- Step 6: Assemble result ----
    outer = classification["outer_stroke_rgb"]
    inner = classification["inner_stroke_rgb"]
    shadow = classification["shadow_rgb"]
    shadow_offset = classification.get("shadow_offset", [0, 0])

    outline_enabled = outer is not None
    outline_rgb = outer if outer else (0, 0, 0)
    outline_type = "dark"
    glow_enabled = False
    glow_rgb = (255, 255, 255)
    outline_width = classification.get("stroke_width_estimate", 0)

    if inner:
        inner_lum = _luminance(inner)
        outer_lum = _luminance(outline_rgb) if outline_enabled else 0
        fill_lum = _luminance(fill_rgb)
        if inner_lum > outer_lum + 10:
            outline_type = "double"
            glow_enabled = True
            glow_rgb = inner
        elif inner_lum > fill_lum + 10:
            outline_type = "glow"
            glow_enabled = True
            glow_rgb = inner

    # Recompute estimated font size
    ys_mask, _ = np.where(mask)
    text_height = max(2, ys_mask.max() - ys_mask.min() + 1) if len(ys_mask) > 0 else 100
    estimated_font_size = max(12, min(300, round(text_height * 0.72)))

    # Weight: median depth of fill cluster ÷ font_size × 6000.
    # The fill cluster's median distance from the text edge directly
    # measures how thick the text body is.  Deeper fill = bolder.
    fill_depth = 0.0
    for s in classification.get("cluster_stats", []):
        if _color_distance(s["centroid_rgb"], fill_rgb) < 10:
            fill_depth = s.get("median_dist", 0)
            break
    if fill_depth > 0 and estimated_font_size > 0:
        estimated_weight = max(100, min(9999, round(fill_depth / max(1, estimated_font_size) * 4000)))
    else:
        estimated_weight = 700

    # Keywords
    keywords: list[str] = []
    if outline_enabled:
        keywords.append("描边")
        if outline_type == "double":
            keywords.append("双层描边")
        elif outline_type == "glow":
            keywords.append("高光边缘")
    if shadow:
        keywords.append("阴影")
    if gradient_enabled:
        keywords.append("渐变")
    if glow_enabled:
        keywords.append("发光")
    if _is_dark(fill_rgb):
        keywords.append("深色字")
    else:
        keywords.append("亮色字")

    effect_count = int(outline_enabled) + int(shadow is not None) + int(gradient_enabled) + int(glow_enabled)
    complexity = "simple" if effect_count <= 1 else ("medium" if effect_count <= 3 else "complex")

    result: dict[str, Any] = {
        "style_id": style_id,
        "style_name": "用户框选花字样式",
        "source_image": source_image,
        "selected_region": {"x": rx, "y": ry, "width": rw, "height": rh},
        "style_type": "custom_flower_text",
        "colors": {
            "fill_color": _rgb_to_hex(*display_fill_rgb),
            "outline_color": _rgb_to_hex(*outline_rgb) if outline_enabled else "",
            "outer_stroke_color": _rgb_to_hex(*outer) if outer else "",
            "inner_stroke_color": _rgb_to_hex(*inner) if inner else "",
            "shadow_color": _rgb_to_hex(*shadow) if shadow else "",
        },
        "effects": {
            "has_outline": outline_enabled,
            "outline_width": int(outline_width),
            "outline_type": outline_type,
            "has_inner_stroke": inner is not None,
            "has_shadow": shadow is not None,
            "shadow_offset": shadow_offset,
            "shadow_blur": 4 if shadow else 0,
            "has_gradient": gradient_enabled,
            "gradient_direction": gradient_direction,
            "has_glow": glow_enabled,
            "has_double_stroke": outline_type == "double",
            "glow_color": _rgb_to_hex(*glow_rgb) if glow_enabled else "",
            "glow_width": int(classification.get("stroke_width_estimate", 2)) // 2 if glow_enabled else 0,
        },
        "style_features": {
            "keywords": keywords,
            "complexity": complexity,
            "estimated_font_size": estimated_font_size,
            "estimated_weight": estimated_weight,
            "stroke_width_px": round(classification.get("stroke_width_estimate", 0), 1),
            "confidence": round(classification.get("confidence", 0), 2),
            "cluster_count": len(centroids_rgb),
        },
        "render_config": {
            "fill": {"color": _rgb_to_hex(*display_fill_rgb)},
            "outer_stroke": {
                "color": _rgb_to_hex(*outer), "width": int(outline_width)
            } if outer else None,
            "inner_stroke": {
                "color": _rgb_to_hex(*inner), "width": max(1, int(outline_width) // 2)
            } if inner else None,
            "shadow": {
                "color": _rgb_to_hex(*shadow),
                "offset": shadow_offset,
                "blur": 4,
            } if shadow else None,
            "effects": {
                "gradient": {
                    "start": _rgb_to_hex(*grad_start),
                    "end": _rgb_to_hex(*grad_end),
                    "direction": gradient_direction,
                } if gradient_enabled else None,
                "glow": {
                    "color": _rgb_to_hex(*glow_rgb), "radius": 2
                } if glow_enabled else None,
            },
        },
        "cluster_details": [
            {
                "cluster_id": s["cluster_id"],
                "hex": _rgb_to_hex(*s["centroid_rgb"]),
                "ratio": round(s["ratio"], 4),
                "median_dist": round(s["median_dist"], 1),
                "luminance": round(s["luminance"], 0),
            }
            for s in classification.get("cluster_stats", [])
        ],
    }

    # ---- Debug output ----
    if debug_dir:
        base = style_id or "style"
        dummy_ratios = [1.0 / len(centroids_rgb)] * len(centroids_rgb) if centroids_rgb else [1.0]
        debug_paths = _make_debug_images(
            bgr, mask, sat_mask, labels_map,
            centroids_rgb, dummy_ratios, classification,
            debug_dir, base,
        )
        result["debug_images"] = debug_paths

    return result


# ---------------------------------------------------------------------------
# description helpers (unchanged API)
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


def _build_visual_desc(*args) -> str:
    return ""   # kept for API compat


def _build_prompt(*args) -> str:
    return ""   # kept for API compat


# ---------------------------------------------------------------------------
# default / file helpers (unchanged API)
# ---------------------------------------------------------------------------

def _default_style(style_id: str, source_image: str,
                   rx: int, ry: int, rw: int, rh: int) -> dict:
    return {
        "style_id": style_id,
        "style_name": "用户框选花字样式",
        "source_image": source_image,
        "selected_region": {"x": rx, "y": ry, "width": rw, "height": rh},
        "style_type": "custom_flower_text",
        "colors": {"fill_color": "#FFFFFF", "outline_color": "",
                   "outer_stroke_color": "", "inner_stroke_color": "", "shadow_color": ""},
        "effects": {"has_outline": False, "outline_width": 0, "outline_type": "dark",
                    "has_inner_stroke": False, "has_shadow": False,
                    "shadow_offset": [0, 0], "shadow_blur": 0,
                    "has_gradient": False, "gradient_direction": "topToBottom",
                    "has_glow": False, "has_double_stroke": False,
                    "glow_color": "", "glow_width": 0},
        "style_features": {"keywords": ["未识别"], "complexity": "simple",
                          "estimated_font_size": 48, "estimated_weight": 700,
                         "stroke_width_px": 0, "confidence": 0.0,
                          "cluster_count": 0},
        "render_config": {"fill": {"color": "#FFFFFF"}, "outer_stroke": None,
                         "inner_stroke": None, "shadow": None,
                         "effects": {"gradient": None, "glow": None}},
    }


def generate_style_id(custom_styles_dir: str) -> str:
    os.makedirs(custom_styles_dir, exist_ok=True)
    existing = [f for f in os.listdir(custom_styles_dir) if f.endswith(".json")]
    idx = len(existing) + 1
    while True:
        sid = f"custom_style_{idx:03d}"
        if not os.path.isfile(os.path.join(custom_styles_dir, f"{sid}.json")):
            return sid
        idx += 1


def save_style_json(style_dict: dict, custom_styles_dir: str) -> str:
    os.makedirs(custom_styles_dir, exist_ok=True)
    sid = style_dict.get("style_id", generate_style_id(custom_styles_dir))
    filepath = os.path.join(custom_styles_dir, f"{sid}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(style_dict, f, ensure_ascii=False, indent=2)
    return filepath


def load_style_json(filepath: str) -> dict | None:
    if not os.path.isfile(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_all_styles(custom_styles_dir: str) -> list[dict]:
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
    outer_stroke = render.get("outer_stroke") or {}
    shadow_info = render.get("shadow") or {}
    features = style_dict.get("style_features", {})

    # Map new keys to old API
    outline_type = effects.get("outline_type", "dark")
    outer_color = colors.get("outer_stroke_color") or colors.get("outline_color", "#000000")
    inner_color = colors.get("inner_stroke_color", "")
    glow_enabled = effects.get("has_glow", False) or effects.get("has_double_stroke", False)
    glow_color = inner_color or effects.get("glow_color", "") or outer_color

    result: dict = {
        "font_family": "Microsoft YaHei",
        "font_size": features.get("estimated_font_size", 48),
        "weight": features.get("estimated_weight", 700),
        "bold": features.get("estimated_weight", 700) >= 600,
        "fill_color": colors.get("fill_color", "#FFFFFF"),
        "stroke_enabled": effects.get("has_outline", False),
        "stroke_color": outer_color,
        "stroke_width": outer_stroke.get("width", effects.get("outline_width", 3)),
        "stroke_mode": outline_type,
        "glow_enabled": glow_enabled,
        "glow_color": glow_color,
        "glow_width": effects.get("glow_width", 2),
        "shadow_enabled": effects.get("has_shadow", False),
        "shadow_color": colors.get("shadow_color", "#000000"),
        "shadow_offset_x": shadow_info.get("offset", effects.get("shadow_offset", [3, 3]))[0],
        "shadow_offset_y": shadow_info.get("offset", effects.get("shadow_offset", [3, 3]))[1],
        "shadow_blur": shadow_info.get("blur", effects.get("shadow_blur", 2)),
        "gradient_enabled": effects.get("has_gradient", False),
        "gradient_start": (render.get("effects", {}).get("gradient") or {}).get("start", "#FFFFFF"),
        "gradient_end": (render.get("effects", {}).get("gradient") or {}).get("end", "#FFD700"),
        "gradient_direction": effects.get("gradient_direction", "topToBottom"),
        "background_enabled": bool(colors.get("background_color", "")),
        "background_color": colors.get("background_color", "#000000"),
        "opacity": 1.0,
    }
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """CLI for batch processing flower-text images."""
    import argparse

    parser = argparse.ArgumentParser(description="花字样式分析工具")
    parser.add_argument("--input", "-i", required=True, help="输入图片路径或目录")
    parser.add_argument("--output", "-o", default="./output", help="输出目录")
    parser.add_argument("--debug", action="store_true", default=True, help="生成 debug 图")
    parser.add_argument("--no-debug", dest="debug", action="store_false", help="不生成 debug 图")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    input_path = args.input
    if os.path.isdir(input_path):
        files = [os.path.join(input_path, f) for f in sorted(os.listdir(input_path))
                 if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif'))]
    else:
        files = [input_path]

    all_results = {}
    for fp in files:
        try:
            img = Image.open(fp)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            base = os.path.splitext(os.path.basename(fp))[0]
            debug_dir = os.path.join(args.output, "debug") if args.debug else ""

            result = analyze_text_style(
                img, region=None, style_id=base,
                source_image=os.path.abspath(fp),
                debug_dir=debug_dir,
            )

            # Save individual JSON
            json_path = os.path.join(args.output, f"{base}_result.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            all_results[base] = result
            print(f"[OK] {base}  confidence={result['style_features']['confidence']:.0%}  "
                  f"fill={result['colors']['fill_color']}  "
                  f"outer={result['colors'].get('outer_stroke_color','none')}  "
                  f"inner={result['colors'].get('inner_stroke_color','none')}")
        except Exception as e:
            print(f"[FAIL] {fp}: {e}")
            continue

    # Summary
    summary_path = os.path.join(args.output, "result.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\nDone. {len(all_results)}/{len(files)} processed. Results in {args.output}")
    if args.debug:
        print(f"Debug images in {os.path.join(args.output, 'debug')}")


if __name__ == "__main__":
    main()
