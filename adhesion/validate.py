"""Deterministic validation of the implemented S13 pipeline."""
from __future__ import annotations

import hashlib
import json

import numpy as np

from . import config, reference, segment
from .pipeline import PairAnalysis


def _loss_mask(analysis: PairAnalysis, params: dict) -> tuple[np.ndarray, dict, dict]:
    state, _ = analysis.ensure_state(params)
    result = segment.detect(state, params)
    return result["loss"], result, state


def _cell_signature(cells: list[dict]) -> str:
    payload = [
        (cell.get("cell_id"), cell.get("loss_pixels"), cell.get("eligible_pixels"), cell.get("status"))
        for cell in cells
    ]
    return hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()


def _ahmed_pair_record(spec: dict) -> dict | None:
    raw = config.ROOT.parent / "Ahmed_ThorCam_Raw_Images_TIFF"
    sample = str(spec.get("sample"))
    index = int(spec.get("index", 0))
    reference_path = raw / sample / f"{sample}_Squared_[{index}].tif"
    taped_path = raw / sample / f"{sample}_Taped_[{index}].tif"
    if not reference_path.exists() or not taped_path.exists():
        return None
    return {
        "id": f"ahmed-{sample}-{index}",
        "label": f"{sample} {index}",
        "mode": "paired",
        "reference": {
            "name": reference_path.name,
            "path": str(reference_path),
            "sha256": spec.get("reference_sha", ""),
        },
        "taped": {
            "name": taped_path.name,
            "path": str(taped_path),
            "sha256": spec.get("taped_sha", ""),
        },
        "reference_spec": spec,
    }


def run_ahmed_validation() -> dict:
    """Reproduce the published Ahmed per-view results with bundled grids.

    The five Ahmed samples were published with different detector settings,
    so each recognised pair starts from its own documented preset.  The check
    confirms that those presets, the supplied cell grids and analysis-domain
    masks reproduce the publication and that repeated runs are identical.
    """
    specs = reference.ahmed_pairs()
    if not specs:
        return {"available": False, "reason": "No bundled Ahmed reference data."}
    rows = []
    samples: dict[str, dict] = {}
    missing = 0
    for spec in specs:
        record = _ahmed_pair_record(spec)
        sample = str(spec.get("sample"))
        index = int(spec.get("index", 0))
        expected = reference.expected_results(spec) or {}
        if record is None:
            missing += 1
            samples.setdefault(sample, {"sample": sample, "views": [], "all_pass": False})
            continue
        analysis = PairAnalysis(record)
        params = analysis.default_params()
        state, _ = analysis.ensure_state(params)
        first = segment.detect(state, params)
        second = segment.detect(state, params)
        stats = first["stats"]
        cells = first["cells"]
        deterministic = bool(
            np.array_equal(first["loss"], second["loss"])
            and _cell_signature(cells) == _cell_signature(second["cells"])
        )
        measured = stats.get("peeled_pct")
        expected_pct = expected.get("peeled_pct")
        error = None if measured is None or expected_pct is None else float(measured) - float(expected_pct)
        eligible_ok = (
            expected.get("eligible_px") is None
            or int(stats.get("eligible_pixels", -1)) == int(expected["eligible_px"])
        )
        passed = bool(
            deterministic
            and eligible_ok
            and error is not None
            and abs(error) <= 0.5
        )
        row = {
            "sample": sample,
            "index": index,
            "expected_pct": expected_pct,
            "measured_pct": measured,
            "error_pp": error,
            "eligible_pixels": stats.get("eligible_pixels"),
            "expected_eligible_px": expected.get("eligible_px"),
            "cells": len(cells),
            "deterministic": deterministic,
            "pass": passed,
        }
        rows.append(row)
        group = samples.setdefault(sample, {"sample": sample, "views": [], "all_pass": True})
        group["views"].append(row)
        group["all_pass"] = bool(group["all_pass"] and passed)

    for sample, group in samples.items():
        values = [row["measured_pct"] for row in group["views"] if row["measured_pct"] is not None]
        expected_values = [
            row["expected_pct"] for row in group["views"] if row["expected_pct"] is not None
        ]
        group["measured_mean_pct"] = float(np.mean(values)) if values else None
        group["expected_mean_pct"] = float(np.mean(expected_values)) if expected_values else None
        group["mean_error_pp"] = (
            None
            if not values or not expected_values
            else group["measured_mean_pct"] - group["expected_mean_pct"]
        )
        group["preset"] = config.AHMED_PRESETS.get(sample)

    singles = []
    single_spec = reference.ahmed_pair("S11", 1)
    if single_spec is not None:
        base = config.ROOT.parent / "Ahmed_ThorCam_Raw_Images_TIFF" / "S11"
        expected_pct = (reference.expected_results(single_spec) or {}).get("peeled_pct")
        for mode, filename, sha_key in (
            ("taped", "S11_Taped_[1].tif", "taped_sha"),
            ("reference", "S11_Squared_[1].tif", "reference_sha"),
        ):
            image_path = base / filename
            if not image_path.exists():
                continue
            record = {
                "id": f"ahmed-single-S11-1-{mode}",
                "label": f"S11 1 {mode}-only",
                "mode": mode,
                "reference": None,
                "taped": None,
                "reference_spec": single_spec,
            }
            record[mode] = {
                "name": image_path.name,
                "path": str(image_path),
                "sha256": single_spec.get(sha_key, ""),
            }
            analysis = PairAnalysis(record)
            params = analysis.default_params()
            prior = (analysis.single or {}).get("reference_prior_pct") if mode == "reference" else None
            state, _ = analysis.ensure_state(params)
            first = segment.detect_single(state, params, mode, prior)
            second = segment.detect_single(state, params, mode, prior)
            singles.append(
                {
                    "mode": mode,
                    "image": filename,
                    "estimate_pct": first["stats"].get("peeled_pct"),
                    "screen_pct": first["stats"].get("screen_pct"),
                    "published_pct": expected_pct,
                    "note": first["stats"].get("estimate_note"),
                    "deterministic": bool(
                        np.array_equal(first["loss"], second["loss"])
                        and first["stats"].get("peeled_pct")
                        == second["stats"].get("peeled_pct")
                    ),
                }
            )

    available = missing == 0
    overall = available and all(group["all_pass"] for group in samples.values())
    return {
        "available": available,
        "reason": None if available else f"{missing} raw Ahmed TIFFs are missing.",
        "pairs": rows,
        "samples": list(samples.values()),
        "singles": singles,
        "max_abs_view_error_pp": max(
            (abs(row["error_pp"]) for row in rows if row["error_pp"] is not None), default=None
        ),
        "all_pass": bool(overall),
    }


def run_validation() -> dict:
    records = [
        reference.s13_demo_pair(
            index,
            identifier=f"demo-s13-{index}",
            label=f"S13 demo {index}",
        )
        for index in range(1, 5)
    ]
    rows = []
    measured = []
    for pair in records:
        index = int(pair.get("reference_spec", {}).get("index", 0))
        analysis = PairAnalysis(pair)
        params = config.merge_params({})
        loss, result, _state = _loss_mask(analysis, params)
        baseline_params = config.merge_params({"detection": {"sensitivity": 1.0}})
        baseline_loss, baseline_result, _ = _loss_mask(analysis, baseline_params)
        expected = reference.expected_results({"sample": "S13", "index": index}) or {}

        # A second, independent call must produce byte-identical masks.
        loss_again, _, _ = _loss_mask(analysis, params)
        deterministic = bool(np.array_equal(loss, loss_again))
        measured_pct = float(result["stats"]["peeled_pct"])
        baseline_pct = float(baseline_result["stats"]["peeled_pct"])
        expected_pct = expected.get("peeled_pct")
        expected_baseline = expected.get("baseline_peeled_pct")
        iou = reference.mask_iou(loss, reference.validation_mask_path(index))
        error = None if expected_pct is None else measured_pct - float(expected_pct)
        baseline_error = None if expected_baseline is None else baseline_pct - float(expected_baseline)
        passed = bool(
            deterministic
            and error is not None
            and abs(error) <= 0.75
            and np.isfinite(iou)
            and iou >= 0.80
            and baseline_error is not None
            and abs(baseline_error) <= 0.30
        )
        measured.append(measured_pct)
        rows.append(
            {
                "index": index,
                "expected_s13_pct": expected_pct,
                "measured_pct": measured_pct,
                "error_pp": error,
                "expected_baseline_pct": expected_baseline,
                "measured_baseline_pct": baseline_pct,
                "baseline_error_pp": baseline_error,
                "mask_iou": None if not np.isfinite(iou) else float(iou),
                "deterministic": deterministic,
                "loss_sha256": hashlib.sha256(loss.tobytes()).hexdigest(),
                "pass": passed,
            }
        )

    mean_measured = float(np.mean(measured))
    s16_mean = reference.reference_mean("S16")
    s18_mean = reference.reference_mean("S18")
    s13_mean = reference.reference_mean("S13")
    s16_difference = None if s16_mean is None else mean_measured - s16_mean
    s18_difference = None if s18_mean is None else mean_measured - s18_mean
    ahmed = run_ahmed_validation()
    s13_pass = bool(
        all(row["pass"] for row in rows)
        and s16_difference is not None
        and abs(s16_difference) <= 3.0
    )
    overall = bool(s13_pass and (not ahmed.get("available") or ahmed.get("all_pass")))
    report = {
        "seed": config.SEED,
        "version": config.PIPELINE_VERSION,
        "method": (
            "S13 paired-image pipeline: affine registration, cut/exclusion masks, "
            "robust log-intensity field, sigma-derived thresholds, 8-connected "
            "components. Default sensitivity is the validated S13 V2 5.0x setting. "
            "Published Ahmed ThorCam pairs use their supplied cell grids and "
            "analysis-domain masks with per-sample detector presets."
        ),
        "input_note": (
            "The original S13/S16 raw TIFFs are not present in the supplied folders. "
            "S13 validation therefore uses inputs reconstructed from the delivered "
            "8-bit Green_Boundaries PNGs. Ahmed validation reads the supplied raw "
            "16-bit TIFFs next to this project; exact raw uploads use their supplied "
            "grid and run the same code path."
        ),
        "criteria": {
            "max_abs_s13_error_pp": 0.75,
            "min_mask_iou": 0.80,
            "max_abs_baseline_error_pp": 0.30,
            "max_abs_s16_difference_pp": 3.0,
            "max_abs_ahmed_view_error_pp": 0.5,
            "ahmed_requires_eligible_exact": True,
        },
        "s13_reference_mean_pct": s13_mean,
        "s16_reference_mean_pct": s16_mean,
        "s18_reference_mean_pct": s18_mean,
        "measured_mean_pct": mean_measured,
        "s16_difference_pp": s16_difference,
        "s18_difference_pp": s18_difference,
        "images": rows,
        "ahmed": ahmed,
        "s13_pass": s13_pass,
        "all_pass": overall,
    }
    return report


def write_validation(path=None) -> dict:
    path = path or (config.ROOT / "validation_report.json")
    report = run_validation()
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(path)
    return report


if __name__ == "__main__":
    result = write_validation()
    print(
        json.dumps(
            {
                "all_pass": result["all_pass"],
                "measured_mean_pct": result["measured_mean_pct"],
                "s13_reference_mean_pct": result["s13_reference_mean_pct"],
                "s16_reference_mean_pct": result["s16_reference_mean_pct"],
                "s18_reference_mean_pct": result["s18_reference_mean_pct"],
                "s16_difference_pp": result["s16_difference_pp"],
                "images": [
                    {
                        "index": row["index"],
                        "expected": row["expected_s13_pct"],
                        "measured": row["measured_pct"],
                        "error_pp": row["error_pp"],
                        "iou": row["mask_iou"],
                        "pass": row["pass"],
                    }
                    for row in result["images"]
                ],
                "ahmed": {
                    "available": result["ahmed"].get("available"),
                    "all_pass": result["ahmed"].get("all_pass"),
                    "samples": [
                        {
                            "sample": group["sample"],
                            "expected_mean_pct": group.get("expected_mean_pct"),
                            "measured_mean_pct": group.get("measured_mean_pct"),
                            "mean_error_pp": group.get("mean_error_pp"),
                            "all_pass": group.get("all_pass"),
                        }
                        for group in result["ahmed"].get("samples", [])
                    ],
                },
            },
            indent=2,
        )
    )
