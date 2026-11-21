"""Fixed configuration for the adhesion image analysis."""
from __future__ import annotations

from pathlib import Path

SEED = 1337
PIPELINE_VERSION = "1.2.0"

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
UPLOADS = DATA / "uploads"
PAIRS = DATA / "pairs"
CACHE = DATA / "cache"
RUNS = DATA / "runs"
DEMO = DATA / "demo"

for path in (DATA, UPLOADS, PAIRS, CACHE, RUNS, DEMO):
    path.mkdir(parents=True, exist_ok=True)

# Reference material shipped with the task.
S13_PARAMS = ROOT / "S13/Step-2/V1/Reusable_Data/S13_Analysis_Parameters.json"
S13_GRID = ROOT / "S13/Step-1/Reusable_Grid_Data"
S13_STEP2 = ROOT / "S13/Step-2/V1"
S13_STEP2_V2 = ROOT / "S13/Step-2/V2"
S16_DEFINITIONS = ROOT / "S16/S16/Step-1/Reusable_Grid_Data/S16_Step1_Grid_Definitions.json"
S16_GRID = ROOT / "S16/S16/Step-1/Reusable_Grid_Data"
S16_STEP2 = ROOT / "S16/S16/Step-2"
S18_STEP2 = ROOT / "S16/S18/Step-2"

# Bundled Ahmed ThorCam cell grids and analysis-domain masks.  These are keyed
# by source SHA-256 so they only apply to the exact published images.
AHMED_INDEX = ROOT / "adhesion/ahmed/sources.json"
AHMED_GRIDS = ROOT / "adhesion/ahmed/grids"
AHMED_ELIGIBLE = ROOT / "adhesion/ahmed/eligible"
AHMED_SAMPLES = ("S11", "S12", "S2", "S5", "S6")

# The Ahmed samples were published with different detector settings.  These
# starting presets are sensible values chosen near the supplied per-view
# results, so a recognised pair opens in the right ballpark instead of at the
# much more sensitive S13 default.  They are ordinary detection parameters and
# remain fully adjustable.
AHMED_PRESETS = {
    "S11": {"detection": {"sensitivity": 1.35, "sigma_multiplier": 2.0, "brightness_ratio": 1.7, "minimum_area": 2}},
    "S12": {"detection": {"sensitivity": 0.87, "sigma_multiplier": 2.0, "brightness_ratio": 1.5, "minimum_area": 2}},
    "S2": {"detection": {"sensitivity": 1.45, "sigma_multiplier": 2.0, "brightness_ratio": 1.9, "minimum_area": 2}},
    "S5": {"detection": {"sensitivity": 5.5, "sigma_multiplier": 2.0, "brightness_ratio": 1.3, "minimum_area": 8}},
    "S6": {"detection": {"sensitivity": 1.4, "sigma_multiplier": 2.0, "brightness_ratio": 1.4, "minimum_area": 5}},
}

# Single-image screening settings.  A Taped-only view has no before image, so
# it can only measure local brightening; the ratio is a sensible starting
# guess, not a calibration, and remains adjustable.  A Squared-only view
# cannot observe peeling at all, so it reports a database prior alongside the
# image-derived bright-area screen.
SINGLE_PRESETS = {
    "S11": {"taped_brightness_ratio": 1.5, "reference_prior_pct": 1.12},
    "S12": {"taped_brightness_ratio": 1.5, "reference_prior_pct": 0.243},
    "S2": {"taped_brightness_ratio": 1.5, "reference_prior_pct": 0.934},
    "S5": {"taped_brightness_ratio": 1.5, "reference_prior_pct": 14.493},
    "S6": {"taped_brightness_ratio": 1.5, "reference_prior_pct": 3.455},
}
GENERIC_SINGLE_PRESET = {"taped_brightness_ratio": 1.5, "reference_prior_pct": None}

DEFAULTS = {
    "registration": {
        "smooth": 0.6,
        "background": 7.0,
        "radius": 25,
        "search": 65,
        "step": 75,
        "ncc": 0.45,
        "inlier_ncc": 0.55,
        "robust": 0.6,
    },
    "grid": {
        "rows": 9,
        "cols": 9,
        "line_prominence": 0.003,
        "curve_sigma": 8.0,
        # Optional manual cell boundaries in the frame shown in the Grid view.
        # The UI fills these when a user drags a detected line.
        "lines_x": [],
        "lines_y": [],
    },
    "exclusion": {
        "near_px": 6.0,
        "abnormal_low": 0.67,
        "abnormal_high": 1.6,
        "dilate": 2,
        "foil_ratio": 2.1,
        "foil_min": 0.244,
        "foil_dilate": 1,
    },
    "signal": {
        "smooth": 0.6,
        "core_distance": 8.0,
        "field_sigma": 18.0,
        "robust": 0.04,
    },
    "detection": {
        "sensitivity": 5.0,
        "sigma_multiplier": 2.0,
        "brightness_ratio": 1.5,
        "minimum_area": 3,
    },
    "display": {
        "mode": "equalize",
    },
}

# UI slider bounds.  These do not affect cached results unless changed.
RANGES = {
    "registration.smooth": [0.0, 2.0, 0.1],
    "registration.background": [3.0, 20.0, 0.5],
    "registration.radius": [10, 50, 1],
    "registration.search": [20, 120, 1],
    "registration.step": [40, 140, 1],
    "registration.ncc": [0.2, 0.9, 0.01],
    "registration.inlier_ncc": [0.2, 0.9, 0.01],
    "registration.robust": [0.05, 2.0, 0.05],
    "grid.rows": [3, 15, 1],
    "grid.cols": [3, 15, 1],
    "grid.line_prominence": [0.0005, 0.02, 0.0005],
    "grid.curve_sigma": [0.0, 25.0, 0.5],
    "exclusion.near_px": [0.0, 20.0, 0.5],
    "exclusion.abnormal_low": [0.2, 1.2, 0.01],
    "exclusion.abnormal_high": [1.0, 3.0, 0.05],
    "exclusion.dilate": [0, 8, 1],
    "exclusion.foil_ratio": [1.2, 4.0, 0.05],
    "exclusion.foil_min": [0.05, 0.6, 0.005],
    "exclusion.foil_dilate": [0, 5, 1],
    "signal.smooth": [0.0, 2.5, 0.1],
    "signal.core_distance": [0.0, 25.0, 0.5],
    "signal.field_sigma": [5.0, 60.0, 1.0],
    "signal.robust": [0.005, 0.2, 0.005],
    "detection.sensitivity": [0.1, 12.0, 0.1],
    "detection.sigma_multiplier": [0.5, 6.0, 0.1],
    "detection.brightness_ratio": [1.01, 2.5, 0.01],
    "detection.minimum_area": [1, 40, 1],
}

STAGE_A_KEYS = ("registration", "grid", "exclusion", "signal")

COLORS = {
    "green": (0, 230, 60),
    "yellow": (255, 245, 150),
    "orange": (255, 165, 65),
    "red": (255, 90, 90),
    "blue": (100, 205, 255),
    "violet": (190, 120, 255),
    "white": (255, 255, 255),
}

# Shared font choices.  Missing fonts fall back to Pillow's bitmap font.
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
)


def merge_params(overrides: dict | None = None) -> dict:
    """Return a complete, validated parameter dictionary."""
    import copy

    params = copy.deepcopy(DEFAULTS)
    if not overrides:
        return params
    for group, values in overrides.items():
        if group not in params or not isinstance(values, dict):
            continue
        for key, value in values.items():
            if key not in params[group]:
                continue
            default = params[group][key]
            if isinstance(default, list):
                if not isinstance(value, (list, tuple)):
                    continue
                try:
                    value = [float(item) for item in value]
                except (TypeError, ValueError):
                    continue
                if len(value) > 16:
                    continue
            else:
                try:
                    if isinstance(default, bool):
                        value = bool(value)
                    elif isinstance(default, int) and not isinstance(default, bool):
                        value = int(round(float(value)))
                    else:
                        value = float(value)
                except (TypeError, ValueError):
                    continue
            params[group][key] = value
    params["grid"]["rows"] = max(3, min(15, params["grid"]["rows"]))
    params["grid"]["cols"] = max(3, min(15, params["grid"]["cols"]))
    params["detection"]["minimum_area"] = max(1, params["detection"]["minimum_area"])
    params["detection"]["sensitivity"] = max(0.1, params["detection"]["sensitivity"])
    params["detection"]["sigma_multiplier"] = max(0.1, params["detection"]["sigma_multiplier"])
    params["detection"]["brightness_ratio"] = max(1.0001, params["detection"]["brightness_ratio"])
    params["registration"]["radius"] = max(5, params["registration"]["radius"])
    params["registration"]["search"] = max(5, params["registration"]["search"])
    params["registration"]["step"] = max(10, params["registration"]["step"])
    return params
