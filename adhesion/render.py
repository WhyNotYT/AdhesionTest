"""Server-side visualisations for every processing step."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi

from . import config


_FONT_CACHE: dict[int, ImageFont.ImageFont] = {}


def font(size: int) -> ImageFont.ImageFont:
    if size not in _FONT_CACHE:
        chosen = None
        for candidate in config.FONT_CANDIDATES:
            try:
                chosen = ImageFont.truetype(candidate, size)
                break
            except OSError:
                continue
        _FONT_CACHE[size] = chosen or ImageFont.load_default()
    return _FONT_CACHE[size]


def _equalize(gray: np.ndarray) -> np.ndarray:
    finite = gray[np.isfinite(gray)]
    if finite.size == 0:
        return np.zeros(gray.shape, dtype=np.float32)
    low, high = np.percentile(finite, [0.5, 99.5])
    if high <= low:
        high = low + 1e-6
    normalised = np.clip((gray - low) / (high - low), 0.0, 1.0)
    # Global histogram equalisation blended with a sqrt tone curve.  The blend
    # keeps the photographic texture legible while still flattening exposure.
    histogram, _ = np.histogram(normalised, bins=1024, range=(0.0, 1.0))
    cdf = np.cumsum(histogram).astype(np.float64)
    cdf /= max(cdf[-1], 1.0)
    equalised = np.interp(normalised, np.linspace(0.0, 1.0, 1024), cdf)
    base = np.sqrt(normalised)
    return (0.62 * equalised + 0.38 * base).astype(np.float32)


def display_gray(gray: np.ndarray, mode: str | None = None) -> np.ndarray:
    mode = mode or config.DEFAULTS["display"]["mode"]
    gray = np.asarray(gray, dtype=np.float32)
    if mode == "sqrt":
        values = np.sqrt(np.clip(gray, 0.0, 1.0))
    elif mode == "linear":
        values = np.clip(gray, 0.0, 1.0)
    else:
        values = _equalize(gray)
    return np.uint8(np.clip(values * 255.0, 0, 255))


def base_rgb(gray: np.ndarray, mode: str | None = None) -> np.ndarray:
    value = display_gray(gray, mode)
    return np.stack([value, value, value], axis=2)


def tint(rgb: np.ndarray, mask: np.ndarray, color, alpha: float) -> np.ndarray:
    if mask is None or not np.any(mask):
        return rgb
    out = rgb.astype(np.float32)
    color = np.asarray(color, dtype=np.float32)
    out[mask] = (1.0 - alpha) * out[mask] + alpha * color
    return np.uint8(np.clip(np.rint(out), 0, 255))


def overlay_boundary(rgb: np.ndarray, boundary: np.ndarray, width: int = 1) -> np.ndarray:
    if boundary is None or not np.any(boundary):
        return rgb
    line = ndi.binary_dilation(boundary, iterations=max(0, width - 1))
    return tint(rgb, line, config.COLORS["green"], 1.0)


def draw_numbers(rgb: np.ndarray, labels: np.ndarray, color=(20, 20, 20)) -> np.ndarray:
    if labels is None or labels.max() == 0:
        return rgb
    image = Image.fromarray(rgb)
    draw = ImageDraw.Draw(image, "RGBA")
    count = int(labels.max())
    text_font = font(18 if rgb.shape[1] >= 1200 else 12)
    for cell_id in range(1, count + 1):
        ys, xs = np.nonzero(labels == cell_id)
        if xs.size == 0:
            continue
        x, y = float(xs.mean()), float(ys.mean())
        text = str(cell_id - 1)
        try:
            box = draw.textbbox((x, y), text, font=text_font, anchor="mm")
            draw.rounded_rectangle(
                (box[0] - 2, box[1] - 1, box[2] + 2, box[3] + 1),
                radius=2,
                fill=(255, 255, 228, 155),
            )
        except Exception:
            pass
        draw.text((x, y), text, font=text_font, anchor="mm", fill=color)
    return np.asarray(image)


def heatmap(values: np.ndarray, mode: str = "delta", limits: tuple[float, float] | None = None) -> np.ndarray:
    data = np.asarray(values, dtype=np.float32)
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return np.zeros((*data.shape, 3), dtype=np.uint8)
    if limits is None:
        low, high = np.percentile(finite, [1.0, 99.0])
        if high <= low:
            high = low + 1e-6
    else:
        low, high = limits
    normalised = np.clip((np.nan_to_num(data, nan=low) - low) / max(high - low, 1e-9), 0.0, 1.0)

    if mode == "delta":
        anchors = np.array(
            [
                [0.00, 20, 28, 38],
                [0.32, 48, 54, 60],
                [0.44, 79, 74, 62],
                [0.55, 169, 122, 54],
                [0.70, 229, 168, 62],
                [1.00, 255, 74, 68],
            ],
            dtype=np.float32,
        )
    elif mode == "field":
        anchors = np.array(
            [
                [0.00, 36, 78, 160],
                [0.35, 85, 160, 205],
                [0.50, 234, 230, 210],
                [0.65, 235, 150, 80],
                [1.00, 170, 35, 45],
            ],
            dtype=np.float32,
        )
    else:
        anchors = np.array(
            [
                [0.00, 8, 18, 38],
                [0.25, 18, 68, 100],
                [0.50, 25, 125, 120],
                [0.72, 115, 180, 80],
                [0.88, 238, 205, 90],
                [1.00, 255, 248, 220],
            ],
            dtype=np.float32,
        )
    positions = anchors[:, 0]
    rgb = np.stack(
        [np.interp(normalised, positions, anchors[:, channel]) for channel in (1, 2, 3)],
        axis=2,
    )
    return np.uint8(np.clip(np.rint(rgb), 0, 255))


def save_png(array: np.ndarray, path: Path, thumb: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(np.asarray(array, dtype=np.uint8))
    if thumb:
        image = image.copy()
        image.thumbnail((420, 315), Image.Resampling.LANCZOS)
    image.save(path)
    return path


def _resize_float(array: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    image = Image.fromarray(np.asarray(array, dtype=np.float32), mode="F")
    return np.asarray(image.resize((shape[1], shape[0]), Image.Resampling.BILINEAR), dtype=np.float32)


def _resize_mask(mask: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    image = Image.fromarray((np.asarray(mask) > 0).astype(np.uint8) * 255, mode="L")
    resized = np.asarray(image.resize((shape[1], shape[0]), Image.Resampling.BOX))
    return resized > 40


def _resize_labels(labels: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    image = Image.fromarray(np.asarray(labels, dtype=np.uint16))
    return np.asarray(image.resize((shape[1], shape[0]), Image.Resampling.NEAREST)).astype(np.uint16)


def _render_scale(state: dict, max_width: int = 1080) -> dict:
    """Downsample only the presentation arrays.  Measurements stay native."""
    height, width = state["tape"].shape
    if width <= max_width:
        return state
    target = (max(1, int(round(height * max_width / width))), max_width)
    scaled = dict(state)
    for key in ("reference_warped", "tape", "delta", "brightness", "field"):
        if key in state:
            scaled[key] = _resize_float(state[key], target)
    for key in ("boundary", "scrape", "old_foil", "valid"):
        if key in state:
            scaled[key] = _resize_mask(state[key], target)
    if "labels" in state:
        scaled["labels"] = _resize_labels(state["labels"], target)
    return scaled


def _scale_result(result: dict, shape: tuple[int, int]) -> dict:
    scaled = dict(result)
    for key in ("loss", "candidate"):
        if key in result:
            scaled[key] = _resize_mask(result[key], shape)
    return scaled


def _registration_overlay(reference_warped: np.ndarray, taped: np.ndarray, mode: str) -> np.ndarray:
    reference_display = display_gray(np.nan_to_num(reference_warped, nan=0.0), mode)
    taped_display = display_gray(taped, mode)
    return np.stack([reference_display, taped_display, taped_display], axis=2)


def _cell_tints(base: np.ndarray, cells: list[dict], labels: np.ndarray) -> np.ndarray:
    status = np.zeros(int(labels.max()) + 1, dtype=np.uint8)
    for cell in cells:
        mask_value = int(cell["mask_value"])
        status[mask_value] = {
            "Intact": 1,
            "Damaged": 2,
            "Excluded": 3,
            "Clear": 1,
            "Bright": 2,
        }.get(cell["status"], 0)
    image = base.copy()
    image = tint(image, status[labels] == 1, config.COLORS["yellow"], 0.23)
    image = tint(image, status[labels] == 2, config.COLORS["orange"], 0.28)
    image = tint(image, status[labels] == 3, config.COLORS["red"], 0.30)
    return image


def render_stage(state: dict, thresholds: dict, output_dir: Path, mode: str) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    state = _render_scale(state)
    tape = state["tape"]
    base = base_rgb(tape, mode)
    labels = state["labels"]
    boundary = state["boundary"]

    views: list[dict] = []

    def add(step: str, key: str, label: str, array: np.ndarray, main: bool = False):
        path = save_png(array, output_dir / f"{key}.png")
        views.append(
            {
                "step": step,
                "key": key,
                "label": label,
                "url": f"/media/{output_dir.relative_to(config.RUNS).as_posix()}/{key}.png",
                "main": main,
            }
        )
        if key in ("overlay", "status", "grid"):
            save_png(array, output_dir / f"{key}_thumb.png", thumb=True)

    reference_display = display_gray(np.nan_to_num(state["reference_warped"], nan=0.0), mode)
    tape_display = display_gray(tape, mode)
    save_png(np.stack([reference_display] * 3, axis=2), output_dir / "reference.png")
    save_png(np.stack([tape_display] * 3, axis=2), output_dir / "tape.png")
    views.extend(
        [
            {
                "step": "align",
                "key": "reference",
                "label": "Squared",
                "url": f"/media/{output_dir.relative_to(config.RUNS).as_posix()}/reference.png",
                "main": False,
            },
            {
                "step": "align",
                "key": "tape",
                "label": "Taped",
                "url": f"/media/{output_dir.relative_to(config.RUNS).as_posix()}/tape.png",
                "main": False,
            },
        ]
    )
    add("align", "align", "Overlay", _registration_overlay(state["reference_warped"], tape, mode), main=True)

    grid_image = tint(base.copy(), labels > 0, config.COLORS["yellow"], 0.23)
    grid_image = overlay_boundary(grid_image, boundary, width=2)
    add("grid", "grid", "Grid", draw_numbers(grid_image, labels), main=True)

    excluded = base.copy()
    excluded = tint(excluded, state["valid"], config.COLORS["yellow"], 0.10)
    excluded = tint(excluded, state["scrape"], config.COLORS["red"], 0.68)
    excluded = tint(excluded, state["old_foil"], config.COLORS["violet"], 0.62)
    excluded = overlay_boundary(excluded, boundary, width=2)
    add("grid", "excluded", "Excluded", excluded)

    corrected = np.nan_to_num(state["reference_warped"], nan=0.0) * np.exp(state["field"])
    normalised = np.stack([display_gray(np.clip(corrected, 0.0, 1.5), mode)] * 3, axis=2)
    add("signals", "normalized", "Reference", normalised, main=False)

    field_image = heatmap(state["field"], "field", limits=(-0.25, 0.25))
    add("signals", "field", "Illumination", field_image)

    delta_limits = (-0.35, 0.75)
    delta_image = heatmap(state["delta"], "delta", limits=delta_limits)
    delta_image[~state["valid"]] = np.uint8(np.clip(base[~state["valid"]] * 0.34 + 28, 0, 255))
    add("signals", "delta", "Delta", delta_image, main=True)

    brightness_image = heatmap(state["brightness"], "brightness", limits=(-0.6, 1.0))
    brightness_image[~state["valid"]] = np.uint8(np.clip(base[~state["valid"]] * 0.34 + 28, 0, 255))
    add("signals", "brightness", "Brightness", brightness_image)

    # Small histograms are drawn client-side; this marker makes the main view
    # identifiable without extra text.
    return views


def render_detection(state: dict, result: dict, output_dir: Path, mode: str) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    state = _render_scale(state)
    result = _scale_result(result, state["tape"].shape)
    tape = state["tape"]
    base = base_rgb(tape, mode)
    labels = state["labels"]
    boundary = state["boundary"]
    loss = result["loss"]
    candidate = result["candidate"]
    thresholds = result["thresholds"]

    views: list[dict] = []

    def add(key: str, label: str, array: np.ndarray, main: bool = False, filename: str | None = None):
        filename = filename or key
        save_png(array, output_dir / f"{filename}.png")
        views.append(
            {
                "step": "loss",
                "key": key,
                "label": label,
                "url": f"/media/{output_dir.relative_to(config.RUNS).as_posix()}/{filename}.png",
                "main": main,
            }
        )
        if filename in ("overlay", "loss", "status"):
            save_png(array, output_dir / f"{filename}_thumb.png", thumb=True)
    loss_image = tint(base.copy(), loss, config.COLORS["blue"], 0.70)
    add("loss", "Loss", loss_image, main=False)

    threshold_image = tint(base.copy(), candidate, config.COLORS["yellow"], 0.30)
    threshold_image = tint(threshold_image, loss, config.COLORS["blue"], 0.78)
    threshold_image = overlay_boundary(threshold_image, boundary, width=2)
    add("thresholds", "Thresholds", threshold_image)

    delta_mask = tint(base.copy(), state["delta"] > thresholds["delta"], config.COLORS["orange"], 0.32)
    delta_mask = overlay_boundary(delta_mask, boundary, width=2)
    add("delta_mask", "Delta mask", delta_mask)

    brightness_mask = tint(base.copy(), state["brightness"] > thresholds["brightness"], config.COLORS["violet"], 0.32)
    brightness_mask = overlay_boundary(brightness_mask, boundary, width=2)
    add("bright_mask", "Brightness mask", brightness_mask)

    status_image = _cell_tints(base.copy(), result["cells"], labels)
    status_image = tint(status_image, loss, config.COLORS["blue"], 0.74)
    status_image = overlay_boundary(status_image, boundary, width=2)
    add("status", "Status", draw_numbers(status_image, labels), main=False)

    overlay_image = _cell_tints(base.copy(), result["cells"], labels)
    overlay_image = tint(overlay_image, loss, config.COLORS["blue"], 0.78)
    overlay_image = overlay_boundary(overlay_image, boundary, width=2)
    overlay_image = draw_numbers(overlay_image, labels)
    add("overlay", "Overlay", overlay_image, main=True)

    return views


def render_single_stage(
    state: dict, thresholds: dict, output_dir: Path, mode: str, display_mode: str
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    state = _render_scale(state)
    image = state["tape"]
    base = base_rgb(image, display_mode)
    labels = state["labels"]
    boundary = state["boundary"]

    views: list[dict] = []

    def add(step: str, key: str, label: str, array: np.ndarray, main: bool = False):
        path = save_png(array, output_dir / f"{key}.png")
        views.append(
            {
                "step": step,
                "key": key,
                "label": label,
                "url": f"/media/{output_dir.relative_to(config.RUNS).as_posix()}/{key}.png",
                "main": main,
            }
        )
        if key in ("grid", "image"):
            save_png(array, output_dir / f"{key}_thumb.png", thumb=True)

    label = "Squared" if mode == "reference" else "Taped"
    add("align", "image", label, base, main=True)

    grid_image = tint(base.copy(), labels > 0, config.COLORS["yellow"], 0.23)
    grid_image = overlay_boundary(grid_image, boundary, width=2)
    add("grid", "grid", "Grid", draw_numbers(grid_image, labels), main=True)

    excluded = base.copy()
    excluded = tint(excluded, state["valid"], config.COLORS["yellow"], 0.10)
    excluded = tint(excluded, state["scrape"], config.COLORS["red"], 0.68)
    excluded = tint(excluded, state["old_foil"], config.COLORS["violet"], 0.62)
    excluded = overlay_boundary(excluded, boundary, width=2)
    add("grid", "excluded", "Excluded", excluded)

    brightness_image = heatmap(state["brightness"], "brightness", limits=(-0.6, 1.0))
    brightness_image[~state["valid"]] = np.uint8(
        np.clip(base[~state["valid"]] * 0.34 + 28, 0, 255)
    )
    add("signals", "brightness", "Brightness", brightness_image)
    return views


def render_single_detection(
    state: dict, result: dict, output_dir: Path, mode: str, display_mode: str
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    state = _render_scale(state)
    result = _scale_result(result, state["tape"].shape)
    base = base_rgb(state["tape"], display_mode)
    labels = state["labels"]
    boundary = state["boundary"]
    bright = result["loss"]
    candidate = result["candidate"]
    thresholds = result["thresholds"]
    color = config.COLORS["blue"] if mode == "taped" else config.COLORS["orange"]
    noun = "Bright candidates" if mode == "taped" else "Bright screen"

    views: list[dict] = []

    def add(key: str, label: str, array: np.ndarray, main: bool = False):
        save_png(array, output_dir / f"{key}.png")
        views.append(
            {
                "step": "loss",
                "key": key,
                "label": label,
                "url": f"/media/{output_dir.relative_to(config.RUNS).as_posix()}/{key}.png",
                "main": main,
            }
        )
        if key in ("overlay", "status"):
            save_png(array, output_dir / f"{key}_thumb.png", thumb=True)

    loss_image = tint(base.copy(), bright, color, 0.70)
    add("loss", noun, loss_image, main=False)

    threshold_image = tint(base.copy(), candidate, config.COLORS["yellow"], 0.30)
    threshold_image = tint(threshold_image, bright, color, 0.78)
    threshold_image = overlay_boundary(threshold_image, boundary, width=2)
    add("thresholds", "Thresholds", threshold_image)

    bright_mask = tint(
        base.copy(), state["brightness"] > thresholds["brightness"], config.COLORS["violet"], 0.32
    )
    bright_mask = overlay_boundary(bright_mask, boundary, width=2)
    add("bright_mask", "Brightness mask", bright_mask)

    status_image = _cell_tints(base.copy(), result["cells"], labels)
    status_image = tint(status_image, bright, color, 0.74)
    status_image = overlay_boundary(status_image, boundary, width=2)
    add("status", "Status", draw_numbers(status_image, labels), main=False)

    overlay_image = _cell_tints(base.copy(), result["cells"], labels)
    overlay_image = tint(overlay_image, bright, color, 0.78)
    overlay_image = overlay_boundary(overlay_image, boundary, width=2)
    overlay_image = draw_numbers(overlay_image, labels)
    add("overlay", "Overlay", overlay_image, main=True)
    return views


def write_cells_heatmap(cells: list[dict], rows: int, cols: int, path: Path) -> Path:
    """Optional PNG heatmap; the UI normally draws this with HTML."""
    size = 640
    canvas = Image.new("RGB", (size, size), (243, 240, 233))
    draw = ImageDraw.Draw(canvas)
    pad = 18
    width = (size - 2 * pad) / cols
    height = (size - 2 * pad) / rows
    label_font = font(13)
    for cell in cells:
        row = cell["row"] - 1
        col = cell["column"] - 1
        value = cell.get("loss_pct") or 0.0
        blend = float(np.clip(value / 20.0, 0.0, 1.0))
        color = (
            int(245 - 80 * blend),
            int(242 - 150 * blend),
            int(225 - 175 * blend),
        )
        x0 = pad + col * width
        y0 = pad + row * height
        draw.rectangle((x0, y0, x0 + width - 2, y0 + height - 2), fill=color)
        draw.text(
            (x0 + width / 2, y0 + height / 2),
            str(cell["cell_id"]),
            font=label_font,
            fill=(35, 35, 35),
            anchor="mm",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)
    return path
