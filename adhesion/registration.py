"""Affine registration of the Squared reference onto the Taped view."""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi, optimize, signal


def _structure(image: np.ndarray, params: dict) -> np.ndarray:
    smooth = float(params.get("smooth", 0.6))
    background = float(params.get("background", 7.0))
    floor = 8.0 / 1023.0
    log_image = np.log(np.maximum(image, floor))
    return ndi.gaussian_filter(log_image, smooth) - ndi.gaussian_filter(log_image, background)


def _ncc_match(reference: np.ndarray, target: np.ndarray, x: int, y: int, radius: int, search: int):
    y0, y1 = y - radius, y + radius + 1
    x0, x1 = x - radius, x + radius + 1
    if y0 < 0 or x0 < 0 or y1 > reference.shape[0] or x1 > reference.shape[1]:
        return None
    template = reference[y0:y1, x0:x1].copy()
    if template.shape != (2 * radius + 1, 2 * radius + 1):
        return None
    template -= template.mean()
    xl, xr = max(0, x - radius - search), min(target.shape[1], x + radius + search + 1)
    yl, yr = max(0, y - radius - search), min(target.shape[0], y + radius + search + 1)
    field = target[yl:yr, xl:xr]
    if field.shape[0] < template.shape[0] or field.shape[1] < template.shape[1]:
        return None
    correlation = signal.fftconvolve(field, template[::-1, ::-1], mode="valid")
    sums = signal.fftconvolve(field, np.ones(template.shape), mode="valid")
    sums2 = signal.fftconvolve(field * field, np.ones(template.shape), mode="valid")
    denominator = np.sqrt(
        np.maximum(sums2 - sums * sums / template.size, 1e-10) * np.sum(template * template)
    )
    correlation = correlation / np.maximum(denominator, 1e-12)
    iy, ix = np.unravel_index(np.argmax(correlation), correlation.shape)
    dx = dy = 0.0
    if 0 < ix < correlation.shape[1] - 1:
        a, b, c = correlation[iy, ix - 1:ix + 2]
        den = a - 2 * b + c
        if np.isfinite(den) and abs(den) > 1e-12:
            dx = float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))
    if 0 < iy < correlation.shape[0] - 1:
        a, b, c = correlation[iy - 1:iy + 2, ix]
        den = a - 2 * b + c
        if np.isfinite(den) and abs(den) > 1e-12:
            dy = float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))
    return [
        float(x),
        float(y),
        float(xl + ix + radius + dx),
        float(yl + iy + radius + dy),
        float(correlation[iy, ix]),
    ]


def _transform(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return np.column_stack([points, np.ones(len(points))]) @ matrix.T


def register(reference: np.ndarray, taped: np.ndarray, params: dict) -> dict:
    """Estimate the affine map reference coordinates -> taped coordinates."""
    radius = int(params.get("radius", 25))
    search = int(params.get("search", 65))
    step = int(params.get("step", 75))
    ncc_min = float(params.get("ncc", 0.45))
    inlier_ncc = float(params.get("inlier_ncc", 0.55))
    robust_scale = float(params.get("robust", 0.6))

    scale = min(reference.shape[0] / 1080.0, reference.shape[1] / 1440.0)
    radius = max(6, int(round(radius * scale)))
    search = max(6, int(round(search * scale)))
    step = max(12, int(round(step * scale)))
    x_start = int(round(300 * reference.shape[1] / 1440.0))
    x_stop = int(round(1251 * reference.shape[1] / 1440.0))
    y_start = int(round(125 * reference.shape[0] / 1080.0))
    y_stop = int(round(981 * reference.shape[0] / 1080.0))

    reference_structure = _structure(reference, params)
    taped_structure = _structure(taped, params)
    matches = []
    for y in range(y_start, y_stop, step):
        for x in range(x_start, x_stop, step):
            found = _ncc_match(reference_structure, taped_structure, x, y, radius, search)
            if found and found[4] > ncc_min:
                matches.append(found)
    matches = np.asarray(matches, dtype=float)
    identity = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    if matches.shape[0] < 4:
        return {
            "matrix": identity,
            "matches": matches.tolist() if matches.size else [],
            "inliers": 0,
            "match_count": int(matches.shape[0]),
            "median_error_px": 0.0,
            "p95_error_px": 0.0,
            "median_ncc": 0.0,
            "warning": "Registration used the identity transform (too few matches).",
        }

    xy = matches[:, :2]
    observed = matches[:, 2:4]
    design = np.column_stack([xy, np.ones(len(xy))])
    initial = np.linalg.lstsq(design, observed, rcond=None)[0].T
    residual = optimize.least_squares(
        lambda values: (_transform(xy, values.reshape(2, 3)) - observed).ravel(),
        initial.ravel(),
        loss="soft_l1",
        f_scale=max(robust_scale, 1e-3),
        max_nfev=100,
    )
    matrix = residual.x.reshape(2, 3)
    errors = np.linalg.norm(_transform(xy, matrix) - observed, axis=1)
    inliers = (errors < 2.5) & (matches[:, 4] > inlier_ncc)
    if int(inliers.sum()) >= 6:
        matrix = np.linalg.lstsq(design[inliers], observed[inliers], rcond=None)[0].T
        errors = np.linalg.norm(_transform(xy, matrix) - observed, axis=1)
    elif int(inliers.sum()) >= 3:
        matrix = np.linalg.lstsq(design[inliers], observed[inliers], rcond=None)[0].T
        errors = np.linalg.norm(_transform(xy, matrix) - observed, axis=1)
    else:
        inliers = errors < 4.0
        if int(inliers.sum()) >= 3:
            matrix = np.linalg.lstsq(design[inliers], observed[inliers], rcond=None)[0].T
            errors = np.linalg.norm(_transform(xy, matrix) - observed, axis=1)

    if not np.all(np.isfinite(matrix)):
        matrix = initial
        errors = np.linalg.norm(_transform(xy, matrix) - observed, axis=1)
        inliers = errors < 4.0
    inlier_errors = errors[inliers] if np.any(inliers) else errors
    result = {
        "matrix": matrix.tolist(),
        "matches": matches.tolist(),
        "inlier_mask": inliers.tolist(),
        "inliers": int(inliers.sum()),
        "match_count": int(matches.shape[0]),
        "median_error_px": float(np.median(inlier_errors)),
        "p95_error_px": float(np.percentile(inlier_errors, 95)),
        "median_ncc": float(np.median(matches[inliers, 4])) if np.any(inliers) else float(np.median(matches[:, 4])),
        "warning": None if int(inliers.sum()) >= 8 else "Few registration inliers; inspect the alignment overlay.",
    }
    return result
