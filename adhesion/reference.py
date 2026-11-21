"""Bundled reference data, expected results and the S13 demo reconstruction."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from . import config
from .io import sha256_file


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _index_from_name(name: str) -> int | None:
    matches = re.findall(r"(?<![\d.])(\d+)(?![\d.])", Path(name).stem)
    if not matches:
        return None
    try:
        return int(matches[-1])
    except ValueError:
        return None


_AHMED_CACHE: dict | None = None


def ahmed_data() -> dict:
    """Bundled Ahmed ThorCam grids, masks and published per-view results."""
    global _AHMED_CACHE
    if _AHMED_CACHE is None:
        if config.AHMED_INDEX.exists():
            try:
                _AHMED_CACHE = json.loads(config.AHMED_INDEX.read_text(encoding="utf-8"))
            except Exception:
                _AHMED_CACHE = {"pairs": []}
        else:
            _AHMED_CACHE = {"pairs": []}
    return _AHMED_CACHE


def ahmed_pairs() -> list[dict]:
    return list(ahmed_data().get("pairs", []))


def ahmed_pair(sample: str, index: int) -> dict | None:
    for item in ahmed_pairs():
        if item.get("sample") == sample and int(item.get("index", 0)) == int(index):
            return {**item, "ahmed": True}
    return None


def ahmed_grid_paths(spec: dict | None) -> tuple[Path, Path, int, int] | None:
    """Return (cell labels, eligible mask, rows, cols) for a known Ahmed view."""
    if not spec:
        return None
    pair = ahmed_pair(str(spec.get("sample", "")), int(spec.get("index", 0) or 0))
    if pair is None:
        return None
    base = config.AHMED_INDEX.parent
    grid = base / pair["grid"]
    eligible = base / pair["eligible"]
    if not grid.exists() or not eligible.exists():
        return None
    return grid, eligible, int(pair.get("rows", 9)), int(pair.get("cols", 9))


def known_sources() -> list[dict]:
    """Return the published source hashes grouped by pair."""
    groups: dict[tuple[str, int], dict] = {}

    if config.S13_PARAMS.exists():
        data = _read_json(config.S13_PARAMS)
        for item in data.get("sources", []):
            name = item.get("filename", "")
            index = _index_from_name(name)
            if index is None:
                continue
            key = ("S13", index)
            groups.setdefault(key, {"sample": "S13", "index": index})
            if "squared" in name.lower():
                groups[key]["reference_sha"] = item.get("sha256")
                groups[key]["reference_name"] = name
            elif "taped" in name.lower():
                groups[key]["taped_sha"] = item.get("sha256")
                groups[key]["taped_name"] = name

    if config.S16_DEFINITIONS.exists():
        data = _read_json(config.S16_DEFINITIONS)
        for item in data.get("images", []):
            index = int(item.get("image", 0))
            key = ("S16", index)
            groups.setdefault(key, {"sample": "S16", "index": index})
            groups[key]["reference_sha"] = item.get("source_sha256")
            groups[key]["reference_name"] = item.get("source_filename")

    for item in ahmed_pairs():
        sample = str(item.get("sample"))
        index = int(item.get("index", 0))
        key = (sample, index)
        groups[key] = {
            "sample": sample,
            "index": index,
            "reference_sha": item.get("reference_sha"),
            "taped_sha": item.get("taped_sha"),
            "reference_name": item.get("reference_name"),
            "taped_name": item.get("taped_name"),
            "ahmed": True,
            "rows": int(item.get("rows", 9)),
            "cols": int(item.get("cols", 9)),
        }

    return list(groups.values())


_SOURCE_CACHE: list[dict] | None = None


def sources() -> list[dict]:
    global _SOURCE_CACHE
    if _SOURCE_CACHE is None:
        _SOURCE_CACHE = known_sources()
    return _SOURCE_CACHE


def lookup_reference(reference_sha: str, taped_sha: str) -> dict | None:
    for item in sources():
        if item.get("reference_sha") != reference_sha:
            continue
        if item["sample"] in ("S13",) or item.get("ahmed"):
            if item.get("taped_sha") != taped_sha:
                continue
        return dict(item)
    return None


def lookup_image(image_sha: str) -> dict | None:
    """Identify one published image (used by the single-image modes)."""
    for item in sources():
        if item.get("reference_sha") == image_sha:
            return {**dict(item), "kind": "reference"}
        if item.get("taped_sha") == image_sha:
            return {**dict(item), "kind": "taped"}
    return None


def expected_results(spec: dict | None) -> dict | None:
    """Published numbers for the matching reference, where available."""
    if not spec:
        return None
    sample = spec.get("sample")
    index = int(spec.get("index", 0))
    if index < 1:
        return None
    out = {
        "sample": sample,
        "index": index,
        "label": f"{sample} {index}",
        "demo": bool(spec.get("demo")),
        "source": None,
        "peeled_pct": None,
        "retained_pct": None,
        "baseline_peeled_pct": None,
        "strict_peeled_pct": None,
    }
    if sample == "S13":
        rows = _csv_rows(config.S13_STEP2_V2 / "S13_Step2_Summary_5x.csv")
        if index <= len(rows):
            row = rows[index - 1]
            out.update(
                peeled_pct=float(row["peeled_AM_pct"]),
                retained_pct=float(row["retained_AM_pct"]),
                baseline_peeled_pct=float(row["baseline_loss_pct"]),
                source="S13 V2 5.0x",
            )
    elif sample == "S16":
        rows = _csv_rows(config.S16_STEP2 / "S16_Step2_Summary.csv")
        if index <= len(rows):
            row = rows[index - 1]
            out.update(
                peeled_pct=float(row["Peeled_AM_percent"]),
                retained_pct=float(row["Retained_AM_percent"]),
                strict_peeled_pct=float(row["Stricter_loss_percent"]),
                source="S16 main",
            )
    elif sample in config.AHMED_SAMPLES:
        pair = ahmed_pair(sample, index)
        if pair is not None:
            expected = pair.get("expected", {})
            out.update(
                peeled_pct=expected.get("peeled_pct"),
                retained_pct=expected.get("retained_pct"),
                eligible_px=expected.get("eligible_px"),
                loss_px=expected.get("loss_px"),
                strict_peeled_pct=expected.get("strict_pct"),
                baseline_peeled_pct=expected.get("baseline_pct"),
                conservative_peeled_pct=expected.get("conservative_pct"),
                permissive_peeled_pct=expected.get("permissive_pct"),
                source=f"{sample} published Step-2",
                rows=int(pair.get("rows", 9)),
                cols=int(pair.get("cols", 9)),
            )
    return out


def detection_preset(spec: dict | None, mode: str = "paired") -> dict:
    """Fixed per-sample detector preset for a recognised published image."""
    if not spec:
        return {}
    sample = spec.get("sample")
    if mode != "paired":
        return {}
    preset = config.AHMED_PRESETS.get(str(sample))
    if not preset:
        return {}
    import copy

    return copy.deepcopy(preset)


def single_preset(spec: dict | None, mode: str) -> dict:
    """Screening settings and database prior for a single-image estimate."""
    sample = str((spec or {}).get("sample", ""))
    preset = dict(config.SINGLE_PRESETS.get(sample, config.GENERIC_SINGLE_PRESET))
    expected = expected_results(spec) if spec else None
    if expected and expected.get("peeled_pct") is not None:
        preset["reference_prior_pct"] = float(expected["peeled_pct"])
        preset["reference_prior_source"] = expected.get("source")
    preset["sample"] = sample or None
    return preset


def reference_mean(sample: str) -> float | None:
    if sample == "S13":
        rows = _csv_rows(config.S13_STEP2_V2 / "S13_Step2_Summary_5x.csv")
        return float(np.mean([float(row["peeled_AM_pct"]) for row in rows]))
    if sample == "S16":
        rows = _csv_rows(config.S16_STEP2 / "S16_Step2_Summary.csv")
        return float(np.mean([float(row["Peeled_AM_percent"]) for row in rows]))
    if sample == "S18":
        rows = _csv_rows(config.S18_STEP2 / "S18_Step2_Adhesion_Summary.csv")
        return float(np.mean([float(row["loss_percent"]) for row in rows]))
    if sample in config.AHMED_SAMPLES:
        values = [
            float(item["expected"]["peeled_pct"])
            for item in ahmed_pairs()
            if item.get("sample") == sample
        ]
        return float(np.mean(values)) if values else None
    return None


def mask_iou(computed: np.ndarray, mask_path: Path) -> float:
    if not mask_path.exists():
        return float("nan")
    reference = np.asarray(Image.open(mask_path)) > 0
    if reference.shape != computed.shape:
        return float("nan")
    union = int(np.logical_or(computed, reference).sum())
    if union == 0:
        return 1.0
    return float(np.logical_and(computed, reference).sum() / union)


# ---------------------------------------------------------------------------
# Demo inputs reconstructed from the delivered 8-bit display PNGs.
# The original raw TIFFs are not part of the supplied folder.  The delivered
# Green_Boundaries PNGs use a known sqrt(raw/1023) display mapping, so the
# underlying ~10-bit signal can be recovered (with 8-bit quantisation) for a
# deterministic end-to-end demo and validation run.
# ---------------------------------------------------------------------------


def _inpaint_nearest(array: np.ndarray, mask: np.ndarray) -> np.ndarray:
    indices = ndi.distance_transform_edt(mask, return_distances=False, return_indices=True)
    return array[tuple(indices)]


def _reconstruct(display_path: Path, boundary_path: Path, destination: Path) -> Path:
    if destination.exists():
        return destination
    rgb = np.asarray(Image.open(display_path).convert("RGB"), dtype=np.float32)
    green = (rgb[..., 1] > 120) & (rgb[..., 1] > rgb[..., 0] * 1.5) & (rgb[..., 1] > rgb[..., 2] * 1.5)
    if boundary_path.exists():
        exact = np.asarray(Image.open(boundary_path)) > 0
        green |= exact
    gray = rgb.mean(axis=2)
    raw = (gray / 255.0) ** 2 * 1023.0
    raw = _inpaint_nearest(raw, green)
    raw = np.clip(raw, 0, 1023)
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.rint(raw).astype(np.uint16)).save(destination)
    return destination


def s13_demo_pair(index: int = 1, identifier: str | None = None, label: str | None = None) -> dict:
    """Create (or reuse) one reconstructed S13 reference view."""
    index = int(max(1, min(4, index)))
    squared = _reconstruct(
        config.ROOT / f"S13/Step-1/S13_Squared_{index}_Green_Boundaries.png",
        config.S13_GRID / f"S13_Squared_{index}_Boundary_Mask.png",
        config.DEMO / f"S13_demo_Squared_[{index}].tif",
    )
    taped = _reconstruct(
        config.S13_STEP2 / f"S13_Taped_{index}_Green_Boundaries.png",
        config.S13_STEP2 / "Reusable_Data" / f"S13_Taped_{index}_Green_Boundary_Mask.png",
        config.DEMO / f"S13_demo_Taped_[{index}].tif",
    )
    spec = {"sample": "S13", "index": index, "demo": True}
    return {
        "id": identifier or f"demo-s13-{index}",
        "label": label or f"S13 demo {index}",
        "reference": {
            "name": squared.name,
            "path": str(squared),
            "sha256": sha256_file(squared),
            "demo": True,
        },
        "taped": {
            "name": taped.name,
            "path": str(taped),
            "sha256": sha256_file(taped),
            "demo": True,
        },
        "reference_spec": spec,
        "expected": expected_results(spec),
    }


def _reconstruct_linear(display_path: Path, destination: Path, low: float, high: float, gamma: float, boundary_path: Path | None = None) -> Path:
    if destination.exists():
        return destination
    rgb = np.asarray(Image.open(display_path).convert("RGB"), dtype=np.float32)
    green = (rgb[..., 1] > 120) & (rgb[..., 1] > rgb[..., 0] * 1.5) & (rgb[..., 1] > rgb[..., 2] * 1.5)
    if boundary_path is not None and boundary_path.exists():
        green |= np.asarray(Image.open(boundary_path)) > 0
    display = np.clip(rgb.mean(axis=2) / 255.0, 0.0, 1.0)
    raw = low + (display ** (1.0 / max(gamma, 1e-6))) * (high - low)
    raw = _inpaint_nearest(raw, green)
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.rint(np.clip(raw, 0, 65535)).astype(np.uint16)).save(destination)
    return destination


def s16_demo_pair(index: int = 1, identifier: str | None = None, label: str | None = None) -> dict:
    """Create (or reuse) one reconstructed S16 reference view."""
    index = int(max(1, min(4, index)))
    definitions = _read_json(config.S16_DEFINITIONS)
    mapping = definitions["images"][index - 1].get("display_mapping", {})
    low = float(mapping.get("low_raw", 13.0))
    high = float(mapping.get("high_raw", 445.0))
    gamma = float(mapping.get("gamma_exponent", 0.8))
    squared = _reconstruct_linear(
        config.ROOT / f"S16/S16/Step-1/S16_Squared_{index}_Green_Boundaries.png",
        config.DEMO / f"S16_demo_Squared_[{index}].tif",
        low,
        high,
        gamma,
    )
    taped = _reconstruct_linear(
        config.ROOT / f"S16/S16/Step-2/S16_Taped_{index}_Green_Boundaries.png",
        config.DEMO / f"S16_demo_Taped_[{index}].tif",
        low,
        high,
        gamma,
    )
    spec = {"sample": "S16", "index": index, "demo": True}
    return {
        "id": identifier or f"demo-s16-{index}",
        "label": label or f"S16 demo {index}",
        "reference": {
            "name": squared.name,
            "path": str(squared),
            "sha256": sha256_file(squared),
            "demo": True,
        },
        "taped": {
            "name": taped.name,
            "path": str(taped),
            "sha256": sha256_file(taped),
            "demo": True,
        },
        "reference_spec": spec,
        "expected": expected_results(spec),
    }

def validation_mask_path(index: int) -> Path:
    return config.S13_STEP2_V2 / "Reusable_Data" / f"S13_Taped_{index}_AM_Loss_Mask_5x.png"
