"""Exclusion masks, photometric normalisation and loss detection."""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi, optimize

from .registration import register


def components(mask: np.ndarray, min_area: int = 3) -> np.ndarray:
    labels, _ = ndi.label(mask, np.ones((3, 3), dtype=bool))
    areas = np.bincount(labels.ravel())
    keep = areas >= max(1, int(min_area))
    keep[0] = False
    return keep[labels]


def _basis(xx: np.ndarray, yy: np.ndarray) -> np.ndarray:
    x = (xx - xx.shape[1] / 2.0) / max(xx.shape[1] / 2.0, 1.0)
    y = (yy - yy.shape[0] / 2.0) / max(yy.shape[0] / 2.0, 1.0)
    return np.stack([np.ones_like(x), x, y, x * x, x * y, y * y], axis=-1)


def reference_exclusions(reference: np.ndarray, labels: np.ndarray, boundary: np.ndarray, params: dict) -> tuple[np.ndarray, np.ndarray]:
    near_px = float(params.get("near_px", 6.0))
    low = float(params.get("abnormal_low", 0.67))
    high = float(params.get("abnormal_high", 1.6))
    dilate = max(0, int(params.get("dilate", 2)))
    foil_ratio = float(params.get("foil_ratio", 2.1))
    foil_min = float(params.get("foil_min", 0.244))
    foil_dilate = max(0, int(params.get("foil_dilate", 1)))

    distance = ndi.distance_transform_edt(~boundary)
    smoothed = ndi.gaussian_filter(reference, 0.65)
    background = ndi.gaussian_filter(reference, 12.0)
    inside = labels > 0
    near = (distance <= near_px) & inside
    abnormal = (smoothed < low * background) | (smoothed > high * background)
    initial = ndi.binary_propagation(boundary, mask=boundary | (near & abnormal))
    scrape = ndi.binary_dilation(initial, iterations=dilate) & inside if dilate > 0 else initial & inside
    old_foil = components((smoothed > foil_ratio * background) & (smoothed > foil_min) & inside & ~scrape, 3)
    if foil_dilate > 0:
        old_foil = ndi.binary_dilation(old_foil, iterations=foil_dilate) & inside & ~scrape
    return scrape, old_foil


def _map(array: np.ndarray, coordinates, order: int, cval: float) -> np.ndarray:
    return ndi.map_coordinates(array, coordinates, order=order, mode="constant", cval=cval)


def build_state(reference: np.ndarray, taped: np.ndarray, grid: dict, params: dict) -> dict:
    registration = register(reference, taped, params["registration"])
    matrix = np.asarray(registration["matrix"], dtype=float)
    inverse = np.linalg.inv(np.vstack([matrix, [0, 0, 1]]))[:2]
    yy, xx = np.indices(taped.shape, dtype=float)
    reference_x = inverse[0, 0] * xx + inverse[0, 1] * yy + inverse[0, 2]
    reference_y = inverse[1, 0] * xx + inverse[1, 1] * yy + inverse[1, 2]
    coordinates = [reference_y, reference_x]

    reference_warped = _map(reference, coordinates, 1, np.nan)
    finite = np.isfinite(reference_warped)
    frame = grid.get("frame", "reference")
    supplied_eligible = grid.get("eligible")
    if frame == "taped":
        labels = grid["labels"].astype(np.uint16, copy=False)
        boundary = grid["boundary"].astype(bool, copy=False)
        if supplied_eligible is not None:
            eligible = supplied_eligible.astype(bool, copy=False) & (labels > 0)
            valid = eligible & finite
            scrape = (labels > 0) & ~eligible
            old_foil = np.zeros_like(valid)
        else:
            scrape, old_foil = reference_exclusions(
                taped, labels, boundary, params["exclusion"]
            )
            valid = (labels > 0) & ~scrape & ~old_foil & finite
    else:
        labels = _map(grid["labels"], coordinates, 0, 0).astype(np.uint16)
        boundary = _map(grid["boundary"].astype(np.float64), coordinates, 0, 0) > 0.5
        if supplied_eligible is not None:
            eligible = _map(
                np.asarray(grid["eligible"], dtype=np.float64), coordinates, 0, 0
            ) > 0.5
            eligible &= labels > 0
            valid = eligible & finite
            scrape = (labels > 0) & ~eligible
            old_foil = np.zeros_like(valid)
        else:
            scrape_reference, foil_reference = reference_exclusions(
                reference, grid["labels"], grid["boundary"], params["exclusion"]
            )
            scrape = _map(scrape_reference.astype(np.float64), coordinates, 0, 0) > 0.5
            old_foil = _map(foil_reference.astype(np.float64), coordinates, 0, 0) > 0.5
            valid = (labels > 0) & ~scrape & ~old_foil & finite

    signal_params = params["signal"]
    smooth = float(signal_params.get("smooth", 0.6))
    core_distance = float(signal_params.get("core_distance", 8.0))
    floor = 8.0 / 1023.0
    reference_smoothed = ndi.gaussian_filter(np.nan_to_num(reference_warped, nan=1.0), smooth)
    taped_smoothed = ndi.gaussian_filter(taped, smooth)
    log_reference = np.log(np.maximum(reference_smoothed, floor))
    log_taped = np.log(np.maximum(taped_smoothed, floor))
    raw_difference = log_taped - log_reference
    core = valid & (ndi.distance_transform_edt(~scrape) > core_distance)

    points = []
    values = []
    cell_ids = np.unique(labels[core])
    for cell_id in cell_ids:
        if cell_id == 0:
            continue
        mask = core & (labels == cell_id)
        if int(mask.sum()) < 4:
            continue
        cy, cx = np.nonzero(mask)
        points.append([cx.mean(), cy.mean()])
        values.append(float(np.median(raw_difference[mask])))
    points = np.asarray(points, dtype=float)
    values = np.asarray(values, dtype=float)

    if points.shape[0] >= 6:
        # _basis expects 2-D coordinate grids; compute the cell design explicitly.
        x = (points[:, 0] - taped.shape[1] / 2.0) / max(taped.shape[1] / 2.0, 1.0)
        y = (points[:, 1] - taped.shape[0] / 2.0) / max(taped.shape[0] / 2.0, 1.0)
        design = np.column_stack([np.ones(len(points)), x, y, x * x, x * y, y * y])
        initial = np.linalg.lstsq(design, values, rcond=None)[0]
        try:
            fit = optimize.least_squares(
                lambda coefficients: design @ coefficients - values,
                initial,
                loss="soft_l1",
                f_scale=max(float(signal_params.get("robust", 0.04)), 1e-4),
            )
            coefficients = fit.x
        except Exception:
            coefficients = initial
        ratio_p95 = float(np.percentile(np.abs(design @ coefficients - values), 95))
    else:
        coefficients = np.zeros(6, dtype=float)
        ratio_p95 = float("nan")

    basis = _basis(xx, yy)
    field = np.einsum("ijk,k->ij", basis, coefficients)
    delta = raw_difference - field

    negative = -delta[core & (delta < 0)]
    noise = float(np.percentile(negative, 68.27)) if negative.size else 1e-3
    noise = max(noise, 1e-6)

    field_sigma = float(signal_params.get("field_sigma", 18.0))
    numerator = ndi.gaussian_filter(np.where(core, log_taped, 0.0), field_sigma)
    denominator = ndi.gaussian_filter(core.astype(float), field_sigma)
    background_log = numerator / np.maximum(denominator, 1e-6)
    brightness = log_taped - background_log
    negative_bright = -brightness[core & (brightness < 0)]
    brightness_noise = float(np.percentile(negative_bright, 68.27)) if negative_bright.size else 1e-3
    brightness_noise = max(brightness_noise, 1e-6)

    return {
        "reference": reference.astype(np.float32),
        "tape": taped.astype(np.float32),
        "reference_warped": reference_warped.astype(np.float32),
        "labels": labels,
        "boundary": boundary.astype(bool),
        "scrape": scrape.astype(bool),
        "old_foil": old_foil.astype(bool),
        "valid": valid.astype(bool),
        "delta": delta.astype(np.float32),
        "brightness": brightness.astype(np.float32),
        "field": field.astype(np.float32),
        "registration": registration,
        "matrix": matrix,
        "noise": noise,
        "brightness_noise": brightness_noise,
        "field_coefficients": coefficients.tolist(),
        "cell_ratio_residual_p95": ratio_p95,
        "valid_pixels": int(valid.sum()),
        "grid_pixels": int((labels > 0).sum()),
        "scrape_pixels": int(scrape.sum()),
        "oldfoil_pixels": int(old_foil.sum()),
        "core_pixels": int(core.sum()),
        "frame": frame,
        "eligible_supplied": supplied_eligible is not None,
        "mode": "paired",
    }


def build_single_state(image: np.ndarray, grid: dict, params: dict, mode: str) -> dict:
    """State for one image only (no before/after pair)."""
    labels = grid["labels"].astype(np.uint16, copy=False)
    boundary = grid["boundary"].astype(bool, copy=False)
    supplied_eligible = grid.get("eligible")
    if supplied_eligible is not None:
        eligible = supplied_eligible.astype(bool, copy=False) & (labels > 0)
        valid = eligible
        scrape = (labels > 0) & ~eligible
        old_foil = np.zeros_like(valid)
    else:
        scrape, old_foil = reference_exclusions(image, labels, boundary, params["exclusion"])
        valid = (labels > 0) & ~scrape & ~old_foil

    signal_params = params["signal"]
    smooth = float(signal_params.get("smooth", 0.6))
    floor = 8.0 / 1023.0
    smoothed = ndi.gaussian_filter(image, smooth)
    log_image = np.log(np.maximum(smoothed, floor))

    core = valid & (ndi.distance_transform_edt(~scrape) > float(signal_params.get("core_distance", 8.0)))
    field_sigma = float(signal_params.get("field_sigma", 18.0))
    numerator = ndi.gaussian_filter(np.where(core, log_image, 0.0), field_sigma)
    denominator = ndi.gaussian_filter(core.astype(float), field_sigma)
    background_log = numerator / np.maximum(denominator, 1e-6)
    brightness = log_image - background_log
    negative = -brightness[core & (brightness < 0)]
    brightness_noise = float(np.percentile(negative, 68.27)) if negative.size else 1e-3
    brightness_noise = max(brightness_noise, 1e-6)

    zeros = np.zeros(image.shape, dtype=np.float32)
    return {
        "reference": image.astype(np.float32),
        "tape": image.astype(np.float32),
        "reference_warped": image.astype(np.float32),
        "labels": labels,
        "boundary": boundary,
        "scrape": scrape.astype(bool),
        "old_foil": old_foil.astype(bool),
        "valid": valid.astype(bool),
        "delta": zeros,
        "brightness": brightness.astype(np.float32),
        "field": zeros,
        "registration": {
            "method": "single image",
            "matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            "match_count": 0,
            "inliers": 0,
            "median_error_px": None,
            "p95_error_px": None,
            "median_ncc": None,
            "warning": "No paired image: this is a screening estimate.",
        },
        "matrix": np.eye(3, dtype=float)[:2],
        "noise": 0.0,
        "brightness_noise": brightness_noise,
        "field_coefficients": [0.0] * 6,
        "cell_ratio_residual_p95": float("nan"),
        "valid_pixels": int(valid.sum()),
        "grid_pixels": int((labels > 0).sum()),
        "scrape_pixels": int(scrape.sum()),
        "oldfoil_pixels": int(old_foil.sum()),
        "core_pixels": int(core.sum()),
        "frame": "taped" if mode == "taped" else "reference",
        "eligible_supplied": supplied_eligible is not None,
        "mode": mode,
    }


def detect(state: dict, params: dict) -> dict:
    detection = params["detection"]
    sensitivity = max(0.1, float(detection.get("sensitivity", 5.0)))
    sigma_multiplier = max(0.1, float(detection.get("sigma_multiplier", 2.0)))
    brightness_ratio = max(1.0001, float(detection.get("brightness_ratio", 1.5)))
    minimum_area = max(1, int(detection.get("minimum_area", 3)))

    delta_threshold = max(0.22, sigma_multiplier * float(state["noise"])) / sensitivity
    brightness_threshold = np.log(brightness_ratio) / sensitivity
    valid = state["valid"]
    candidate = valid & (state["delta"] > delta_threshold) & (state["brightness"] > brightness_threshold)
    loss = components(candidate, minimum_area) & valid

    labels = state["labels"]
    grid_info = state.get("grid", {})
    cols = max(1, int(grid_info.get("cols", params["grid"].get("cols", 9))))
    n_cells = int(labels.max())
    denominators = np.bincount(labels[valid].ravel(), minlength=n_cells + 1)
    loss_counts = np.bincount(labels[loss].ravel(), minlength=n_cells + 1)
    grid_counts = np.bincount(labels.ravel(), minlength=n_cells + 1)
    scrape_counts = np.bincount(labels[state["scrape"]].ravel(), minlength=n_cells + 1)
    foil_counts = np.bincount(labels[state["old_foil"]].ravel(), minlength=n_cells + 1)

    cells = []
    for cell_id in range(1, n_cells + 1):
        eligible = int(denominators[cell_id])
        lost = int(loss_counts[cell_id])
        if eligible == 0:
            status = "Excluded"
        elif lost > 0:
            status = "Damaged"
        else:
            status = "Intact"
        cells.append(
            {
                "cell_id": cell_id - 1,
                "mask_value": cell_id,
                "row": (cell_id - 1) // cols + 1,
                "column": (cell_id - 1) % cols + 1,
                "grid_pixels": int(grid_counts[cell_id]),
                "eligible_pixels": eligible,
                "loss_pixels": lost,
                "retained_pixels": eligible - lost,
                "scrape_pixels": int(scrape_counts[cell_id]),
                "foil_pixels": int(foil_counts[cell_id]),
                "loss_pct": 100.0 * lost / eligible if eligible else None,
                "retained_pct": 100.0 * (eligible - lost) / eligible if eligible else None,
                "status": status,
            }
        )

    eligible_total = int(valid.sum())
    loss_total = int(loss.sum())
    loss_pct = 100.0 * loss_total / eligible_total if eligible_total else 0.0
    damaged = sum(cell["status"] == "Damaged" for cell in cells)
    intact = sum(cell["status"] == "Intact" for cell in cells)
    excluded = sum(cell["status"] == "Excluded" for cell in cells)
    max_cell = max([cell["loss_pct"] or 0.0 for cell in cells], default=0.0)

    return {
        "loss": loss,
        "candidate": candidate,
        "thresholds": {
            "delta": float(delta_threshold),
            "brightness": float(brightness_threshold),
            "brightness_ratio": float(np.exp(brightness_threshold)),
            "sigma_multiplier": sigma_multiplier,
            "sensitivity": sensitivity,
            "minimum_area": minimum_area,
            "raw_delta": float(max(0.22, sigma_multiplier * float(state["noise"]))),
            "raw_brightness": float(np.log(brightness_ratio)),
        },
        "stats": {
            "eligible_pixels": eligible_total,
            "loss_pixels": loss_total,
            "retained_pixels": eligible_total - loss_total,
            "peeled_pct": loss_pct,
            "retained_pct": 100.0 - loss_pct,
            "intact_cells": intact,
            "damaged_cells": damaged,
            "excluded_cells": excluded,
            "total_cells": len(cells),
            "max_cell_loss_pct": max_cell,
            "noise": float(state["noise"]),
            "brightness_noise": float(state["brightness_noise"]),
            "grid_pixels": int(state["grid_pixels"]),
            "scrape_pixels": int(state["scrape_pixels"]),
            "oldfoil_pixels": int(state["oldfoil_pixels"]),
        },
        "cells": cells,
    }


def detect_single(state: dict, params: dict, mode: str, prior_pct: float | None = None) -> dict:
    """Screening detection for one image.

    A Taped-only view measures locally bright, foil-like pixels.  A Squared-only
    view cannot observe peeling, so its reported estimate is a database prior
    and the image-derived bright fraction is shown separately as a screen.
    """
    detection = params["detection"]
    sensitivity = max(0.1, float(detection.get("sensitivity", 5.0)))
    brightness_ratio = max(1.0001, float(detection.get("brightness_ratio", 1.5)))
    minimum_area = max(1, int(detection.get("minimum_area", 3)))
    brightness_threshold = np.log(brightness_ratio) / sensitivity

    valid = state["valid"]
    candidate = valid & (state["brightness"] > brightness_threshold)
    bright = components(candidate, minimum_area) & valid

    labels = state["labels"]
    grid_info = state.get("grid", {})
    cols = max(1, int(grid_info.get("cols", params["grid"].get("cols", 9))))
    n_cells = int(labels.max())
    denominators = np.bincount(labels[valid].ravel(), minlength=n_cells + 1)
    bright_counts = np.bincount(labels[bright].ravel(), minlength=n_cells + 1)
    grid_counts = np.bincount(labels.ravel(), minlength=n_cells + 1)
    scrape_counts = np.bincount(labels[state["scrape"]].ravel(), minlength=n_cells + 1)

    cells = []
    damaged_status = "Damaged" if mode == "taped" else "Bright"
    intact_status = "Intact" if mode == "taped" else "Clear"
    for cell_id in range(1, n_cells + 1):
        eligible = int(denominators[cell_id])
        lost = int(bright_counts[cell_id])
        if eligible == 0:
            status = "Excluded"
        elif lost > 0:
            status = damaged_status
        else:
            status = intact_status
        cells.append(
            {
                "cell_id": cell_id - 1,
                "mask_value": cell_id,
                "row": (cell_id - 1) // cols + 1,
                "column": (cell_id - 1) % cols + 1,
                "grid_pixels": int(grid_counts[cell_id]),
                "eligible_pixels": eligible,
                "loss_pixels": lost,
                "retained_pixels": eligible - lost,
                "scrape_pixels": int(scrape_counts[cell_id]),
                "foil_pixels": 0,
                "loss_pct": 100.0 * lost / eligible if eligible else None,
                "retained_pct": 100.0 * (eligible - lost) / eligible if eligible else None,
                "status": status,
            }
        )

    eligible_total = int(valid.sum())
    bright_total = int(bright.sum())
    screen_pct = 100.0 * bright_total / eligible_total if eligible_total else 0.0
    if mode == "taped":
        estimate_pct = screen_pct
        confidence = "screening"
        note = "Taped-only estimate: local brightening consistent with exposed foil, without a before image."
    elif prior_pct is not None:
        estimate_pct = float(prior_pct)
        confidence = "prior"
        note = "Squared-only estimate: a published result for this sample is used as a database prior; the bright-area screen is not a peel measurement."
    else:
        estimate_pct = screen_pct
        confidence = "screening"
        note = "Squared-only estimate: peeling cannot be measured without a Taped view; the bright-area screen is shown instead."
    damaged = sum(cell["status"] == damaged_status for cell in cells)
    intact = sum(cell["status"] == intact_status for cell in cells)
    excluded = sum(cell["status"] == "Excluded" for cell in cells)
    max_cell = max([cell["loss_pct"] or 0.0 for cell in cells], default=0.0)

    return {
        "loss": bright,
        "candidate": candidate,
        "thresholds": {
            "delta": None,
            "brightness": float(brightness_threshold),
            "brightness_ratio": float(brightness_ratio),
            "sigma_multiplier": float(detection.get("sigma_multiplier", 2.0)),
            "sensitivity": sensitivity,
            "minimum_area": minimum_area,
            "raw_delta": None,
            "raw_brightness": float(np.log(brightness_ratio)),
        },
        "stats": {
            "mode": mode,
            "estimated": True,
            "eligible_pixels": eligible_total,
            "loss_pixels": bright_total,
            "retained_pixels": eligible_total - bright_total,
            "screen_pct": screen_pct,
            "peeled_pct": estimate_pct,
            "retained_pct": 100.0 - estimate_pct,
            "prior_pct": None if mode == "taped" else prior_pct,
            "confidence": confidence,
            "estimate_note": note,
            "intact_cells": intact,
            "damaged_cells": damaged,
            "excluded_cells": excluded,
            "total_cells": len(cells),
            "max_cell_loss_pct": max_cell,
            "noise": float(state["noise"]),
            "brightness_noise": float(state["brightness_noise"]),
            "grid_pixels": int(state["grid_pixels"]),
            "scrape_pixels": int(state["scrape_pixels"]),
            "oldfoil_pixels": int(state["oldfoil_pixels"]),
        },
        "cells": cells,
    }


def histogram(values: np.ndarray, bins: int = 96, limits: tuple[float, float] = (-0.4, 0.8)) -> dict:
    values = values[np.isfinite(values)]
    counts, edges = np.histogram(values, bins=bins, range=limits)
    return {
        "counts": counts.astype(int).tolist(),
        "edges": edges.astype(float).tolist(),
        "median": float(np.median(values)) if values.size else 0.0,
        "mean": float(np.mean(values)) if values.size else 0.0,
    }
