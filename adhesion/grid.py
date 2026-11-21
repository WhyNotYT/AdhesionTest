"""Cell grid loading and automatic grid detection."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi, signal

from . import config


def _centroids(labels: np.ndarray) -> list[dict]:
    n = int(labels.max())
    cells = []
    for cell_id in range(1, n + 1):
        ys, xs = np.nonzero(labels == cell_id)
        if xs.size == 0:
            continue
        cells.append(
            {
                "mask_value": cell_id,
                "cell_id": cell_id - 1,
                "centroid": [float(xs.mean()), float(ys.mean())],
                "area": int(xs.size),
            }
        )
    return cells


def _finish(
    labels: np.ndarray,
    boundary: np.ndarray,
    rows: int,
    cols: int,
    method: str,
    extra: dict | None = None,
    eligible: np.ndarray | None = None,
    frame: str = "reference",
) -> dict:
    labels = labels.astype(np.uint16, copy=False)
    boundary = boundary.astype(bool, copy=False)
    cells = _centroids(labels)
    for cell in cells:
        index = int(cell["cell_id"])
        cell["row"] = index // cols + 1
        cell["column"] = index % cols + 1
    info = {"method": method, "rows": rows, "cols": cols, "cells": cells, "frame": frame}
    if extra:
        info.update(extra)
    return {
        "labels": labels,
        "boundary": boundary,
        "eligible": None if eligible is None else np.asarray(eligible, dtype=bool),
        "frame": frame,
        "info": info,
    }


def _derive_boundary(labels: np.ndarray) -> np.ndarray:
    """One-pixel cut centerlines from a cell-label mask."""
    labels = labels.astype(np.uint16, copy=False)
    boundary = np.zeros(labels.shape, dtype=bool)
    boundary[:, 1:] |= labels[:, 1:] != labels[:, :-1]
    boundary[:, :-1] |= labels[:, :-1] != labels[:, 1:]
    boundary[1:, :] |= labels[1:, :] != labels[:-1, :]
    boundary[:-1, :] |= labels[:-1, :] != labels[1:, :]
    return boundary


def load_reference_grid(spec: dict | None, rows: int, cols: int, image_shape: tuple[int, int]) -> dict | None:
    """Load supplied grid masks when an uploaded pair matches a known source."""
    if not spec:
        return None
    sample = spec.get("sample")
    index = int(spec.get("index", 0))
    if index < 1:
        return None
    height, width = image_shape

    if sample == "S13" and rows == 9 and cols == 9:
        label_path = config.S13_GRID / f"S13_Squared_{index}_Cell_ID_Mask.tif"
        boundary_path = config.S13_GRID / f"S13_Squared_{index}_Boundary_Mask.png"
        if not label_path.exists() or not boundary_path.exists():
            return None
        labels = np.asarray(Image.open(label_path))
        boundary = np.asarray(Image.open(boundary_path)) > 0
        if labels.shape != (height, width):
            return None
        return _finish(labels, boundary, rows, cols, "S13 supplied grid", {"reference": f"S13 {index}"})

    if sample == "S16" and rows == 9 and cols == 9:
        label_path = config.S16_GRID / f"S16_Squared_{index}_Cell_IDs_1-81.png"
        if not label_path.exists() or not config.S16_DEFINITIONS.exists():
            return None
        labels = np.asarray(Image.open(label_path))
        if labels.shape != (height, width):
            return None
        definitions = json.loads(config.S16_DEFINITIONS.read_text(encoding="utf-8"))
        entry = definitions["images"][index - 1]
        canvas = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(canvas)
        for line in entry.get("horizontal_boundary_paths_px", []) + entry.get("vertical_boundary_paths_px", []):
            points = [(float(p[0]), float(p[1])) for p in line]
            if len(points) >= 2:
                draw.line(points, fill=255, width=2)
        boundary = np.asarray(canvas) > 0
        return _finish(labels, boundary, rows, cols, "S16 supplied grid", {"reference": f"S16 {index}"})

    return None


def load_ahmed_grid(
    spec: dict | None, image_shape: tuple[int, int], rows: int, cols: int
) -> dict | None:
    """Load the bundled Ahmed cell labels and analysis-domain mask.

    The published Ahmed grids are defined in the native Taped frame, so the
    labels are used directly rather than being warped with the reference.
    Changing the row/column count falls back to automatic detection.
    """
    if not spec:
        return None
    from . import reference

    paths = reference.ahmed_grid_paths(spec)
    if paths is None:
        return None
    label_path, eligible_path, grid_rows, grid_cols = paths
    if (int(rows), int(cols)) != (grid_rows, grid_cols):
        return None
    height, width = image_shape
    try:
        labels = np.asarray(Image.open(label_path))
        eligible = np.asarray(Image.open(eligible_path)) > 0
    except Exception:
        return None
    if labels.ndim == 3:
        labels = labels[..., 0]
    labels = labels.astype(np.uint16)
    if labels.shape != (height, width) or eligible.shape != (height, width):
        return None
    if int(labels.max()) != grid_rows * grid_cols:
        return None
    eligible = eligible & (labels > 0)
    boundary = _derive_boundary(labels)
    return _finish(
        labels,
        boundary,
        grid_rows,
        grid_cols,
        f"{spec.get('sample')} supplied grid",
        {"reference": f"{spec.get('sample')} {spec.get('index')}", "eligible_pixels": int(eligible.sum())},
        eligible=eligible,
        frame="taped",
    )


def _select_lines(values: np.ndarray, prominences: np.ndarray, count: int, min_prominence: float) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(values)
    values = values[order].astype(float)
    prominences = prominences[order].astype(float)
    if values.size > count:
        threshold = max(min_prominence * 1.5, float(np.median(prominences)) * 0.15)
        keep = prominences >= threshold
        if int(keep.sum()) >= count:
            values = values[keep]
            prominences = prominences[keep]
    if values.size == count:
        return values, prominences
    if values.size > count:
        best = None
        for start in range(values.size - count + 1):
            window = values[start:start + count]
            proms = prominences[start:start + count]
            gaps = np.diff(window)
            if np.any(gaps <= 1):
                continue
            pitch = float(np.median(gaps))
            regularity = float(np.std(gaps) / max(pitch, 1e-9))
            score = float(np.sum(np.log1p(np.maximum(proms, 0)))) - 5.0 * regularity
            if np.min(proms) < min_prominence * 0.25:
                score -= 2.0
            if best is None or score > best[0]:
                best = (score, window, proms)
        if best is not None:
            return best[1], best[2]

    if values.size >= 2:
        gaps = np.diff(values)
        pitch = float(np.median(gaps[gaps > 1])) if np.any(gaps > 1) else float(values[-1] - values[0]) / max(count - 1, 1)
        pitch = max(pitch, 4.0)
        centre = float(np.median(values))
        start = centre - pitch * (count - 1) / 2.0
        generated = start + pitch * np.arange(count)
        # Blend towards observed peaks when they are close to the regular slots.
        for obs in values:
            slot = int(round((obs - start) / pitch))
            if 0 <= slot < count:
                generated[slot] = obs
        return generated, np.full(count, max(min_prominence, float(np.max(prominences, initial=0.0))))

    start = 0.28
    pitch = 0.054
    return np.linspace(start, start + pitch * (count - 1), count), np.full(count, min_prominence)


def _refine_vertical(response: np.ndarray, base: float, y0: int, y1: int, curve_sigma: float) -> tuple[np.ndarray, np.ndarray]:
    height, width = response.shape
    y0 = max(0, int(y0))
    y1 = min(height - 1, int(y1))
    rows = np.arange(y0, y1 + 1)
    xs = np.empty(rows.size, dtype=float)
    half = 9
    for idx, y in enumerate(rows):
        lo = max(0, int(round(base)) - half)
        hi = min(width, int(round(base)) + half + 1)
        xs[idx] = lo + float(np.argmax(response[y, lo:hi]))
    if curve_sigma > 0 and xs.size > 3:
        xs = ndi.gaussian_filter1d(xs, max(0.5, curve_sigma), mode="nearest")
    xs = np.clip(xs, max(0, base - half), min(width - 1, base + half))
    return rows, xs


def _refine_horizontal(response: np.ndarray, base: float, x0: int, x1: int, curve_sigma: float) -> tuple[np.ndarray, np.ndarray]:
    height, width = response.shape
    x0 = max(0, int(x0))
    x1 = min(width - 1, int(x1))
    cols = np.arange(x0, x1 + 1)
    ys = np.empty(cols.size, dtype=float)
    half = 9
    for idx, x in enumerate(cols):
        lo = max(0, int(round(base)) - half)
        hi = min(height, int(round(base)) + half + 1)
        ys[idx] = lo + float(np.argmax(response[lo:hi, x]))
    if curve_sigma > 0 and ys.size > 3:
        ys = ndi.gaussian_filter1d(ys, max(0.5, curve_sigma), mode="nearest")
    ys = np.clip(ys, max(0, base - half), min(height - 1, base + half))
    return cols, ys


def _paint_paths(vertical: list[tuple[np.ndarray, np.ndarray]], horizontal: list[tuple[np.ndarray, np.ndarray]], shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    boundary = np.zeros(shape, dtype=bool)
    for rows, xs in vertical:
        for y, x in zip(rows.astype(int), np.rint(xs).astype(int)):
            if 0 <= y < height and 0 <= x < width:
                boundary[y, x] = True
    for cols, ys in horizontal:
        for x, y in zip(cols.astype(int), np.rint(ys).astype(int)):
            if 0 <= x < width and 0 <= y < height:
                boundary[y, x] = True
    return boundary


def _straight_labels(xs: np.ndarray, ys: np.ndarray, rows: int, cols: int, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    height, width = shape
    labels = np.zeros(shape, dtype=np.uint16)
    boundary = np.zeros(shape, dtype=bool)
    x0, x1 = int(round(xs[0])), int(round(xs[-1]))
    y0, y1 = int(round(ys[0])), int(round(ys[-1]))
    x0, x1 = max(0, x0), min(width - 1, x1)
    y0, y1 = max(0, y0), min(height - 1, y1)
    for x in np.rint(xs).astype(int):
        if 0 <= x < width:
            boundary[y0:y1 + 1, x] = True
    for y in np.rint(ys).astype(int):
        if 0 <= y < height:
            boundary[y, x0:x1 + 1] = True
    y_grid = np.clip(np.rint(ys).astype(int), 0, height - 1)
    x_grid = np.clip(np.rint(xs).astype(int), 0, width - 1)
    for y in range(y0, y1 + 1):
        row = int(np.searchsorted(y_grid, y, side="right") - 1)
        if row < 0 or row >= rows:
            continue
        for x in range(x0, x1 + 1):
            col = int(np.searchsorted(x_grid, x, side="right") - 1)
            if col < 0 or col >= cols:
                continue
            labels[y, x] = row * cols + col + 1
    labels[boundary] = 0
    return labels, boundary


def detect_grid(image: np.ndarray, rows: int, cols: int, params: dict | None = None) -> dict:
    """Detect the cut grid and label cells, without external grid data."""
    params = params or config.DEFAULTS["grid"]
    height, width = image.shape
    scale = min(height, width) / 1080.0
    floor = 8.0 / 1023.0
    log_image = np.log(np.maximum(image, floor))

    sigma_cross = max(0.6 * scale, 0.3)
    sigma_long = max(2.0 * scale, 0.5)
    sigma_bg = max(4.0 * scale, 2.0)
    vertical_response = np.abs(
        ndi.gaussian_filter(log_image, (sigma_long, sigma_cross))
        - ndi.gaussian_filter(log_image, (sigma_long, sigma_bg))
    )
    horizontal_response = np.abs(
        ndi.gaussian_filter(log_image, (sigma_cross, sigma_long))
        - ndi.gaussian_filter(log_image, (sigma_bg, sigma_long))
    )

    y_lo, y_hi = int(0.12 * height), int(0.88 * height)
    x_lo, x_hi = int(0.18 * width), int(0.86 * width)
    vertical_profile = ndi.gaussian_filter1d(np.mean(vertical_response[y_lo:y_hi, :], axis=0), 1.0)
    horizontal_profile = ndi.gaussian_filter1d(np.mean(horizontal_response[:, x_lo:x_hi], axis=1), 1.0)

    x_search = slice(int(0.18 * width), int(0.87 * width))
    y_search = slice(int(0.06 * height), int(0.94 * height))
    px, x_props = signal.find_peaks(
        vertical_profile[x_search],
        distance=max(8, int(0.035 * width)),
        prominence=float(params.get("line_prominence", 0.003)),
    )
    py, y_props = signal.find_peaks(
        horizontal_profile[y_search],
        distance=max(8, int(0.035 * height)),
        prominence=float(params.get("line_prominence", 0.003)),
    )
    px = px + int(0.18 * width)
    py = py + int(0.06 * height)
    xs, _ = _select_lines(px.astype(float), x_props.get("prominences", np.array([])), cols + 1, float(params.get("line_prominence", 0.003)))
    ys, _ = _select_lines(py.astype(float), y_props.get("prominences", np.array([])), rows + 1, float(params.get("line_prominence", 0.003)))

    if xs.size != cols + 1 or ys.size != rows + 1 or np.any(np.diff(xs) <= 1) or np.any(np.diff(ys) <= 1):
        # Last-resort regular grid over the central area.
        xs = np.linspace(0.28 * width, 0.80 * width, cols + 1)
        ys = np.linspace(0.15 * height, 0.84 * height, rows + 1)

    curve_sigma = float(params.get("curve_sigma", 8.0))
    vertical_paths = [
        _refine_vertical(vertical_response, float(x), int(ys[0]) - 6, int(ys[-1]) + 6, curve_sigma)
        for x in xs
    ]
    horizontal_paths = [
        _refine_horizontal(horizontal_response, float(y), int(xs[0]) - 6, int(xs[-1]) + 6, curve_sigma)
        for y in ys
    ]
    boundary_center = _paint_paths(vertical_paths, horizontal_paths, image.shape)
    boundary = ndi.binary_dilation(boundary_center, iterations=1)

    structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
    components, count = ndi.label(~boundary, structure=structure)
    sizes = np.bincount(components.ravel())
    sizes[0] = 0
    expected_area = ((xs[-1] - xs[0]) / max(cols, 1)) * ((ys[-1] - ys[0]) / max(rows, 1))
    centroids = ndi.center_of_mass(np.ones_like(components), components, range(1, count + 1)) if count else []
    candidates = []
    for component_id in range(1, count + 1):
        area = int(sizes[component_id])
        if area < 0.30 * expected_area or area > 1.75 * expected_area:
            continue
        cy, cx = centroids[component_id - 1]
        if xs[0] - 8 <= cx <= xs[-1] + 8 and ys[0] - 8 <= cy <= ys[-1] + 8:
            candidates.append((component_id, cx, cy, area))

    if len(candidates) == rows * cols:
        candidates.sort(key=lambda item: (int(np.searchsorted(ys, item[2])), item[1]))
        labels = np.zeros(image.shape, dtype=np.uint16)
        for index, (component_id, _cx, _cy, _area) in enumerate(candidates):
            labels[components == component_id] = index + 1
        return _finish(
            labels,
            boundary,
            rows,
            cols,
            "automatic",
            {"lines_x": xs.tolist(), "lines_y": ys.tolist(), "cell_count": len(candidates)},
        )

    labels, boundary_center = _straight_labels(xs, ys, rows, cols, image.shape)
    return _finish(
        labels,
        ndi.binary_dilation(boundary_center, iterations=1),
        rows,
        cols,
        "automatic (regular fallback)",
        {"lines_x": xs.tolist(), "lines_y": ys.tolist(), "cell_count": rows * cols},
    )


def make_grid(
    image: np.ndarray,
    spec: dict | None,
    params: dict,
    taped_shape: tuple[int, int] | None = None,
) -> dict:
    rows = int(params.get("rows", 9))
    cols = int(params.get("cols", 9))
    if taped_shape is not None:
        ahmed = load_ahmed_grid(spec, taped_shape, rows, cols)
        if ahmed is not None:
            return ahmed
    supplied = load_reference_grid(spec, rows, cols, image.shape)
    if supplied is not None:
        return supplied
    return detect_grid(image, rows, cols, params)
