"""Cached, deterministic analysis pipeline."""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import numpy as np
from PIL import Image

from . import config, grid as grid_module, reference as reference_module, render, segment
from .io import read_gray

np.random.seed(config.SEED)
random.seed(config.SEED)


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _hash(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:20]


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
        return value if np.isfinite(value) else None
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


class PairAnalysis:
    def __init__(self, pair: dict):
        self.pair = pair
        self.pair_id = pair["id"]
        self.cache_dir = config.CACHE / self.pair_id
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.mode = pair.get("mode", "paired")
        if self.mode not in ("paired", "reference", "taped"):
            self.mode = "paired"
        self.spec = pair.get("reference_spec")
        if self.spec is None:
            if self.mode == "paired":
                self.spec = reference_module.lookup_reference(
                    pair["reference"].get("sha256", ""), pair["taped"].get("sha256", "")
                )
            else:
                image = pair.get(self.mode, {})
                self.spec = reference_module.lookup_image(image.get("sha256", ""))
        self.expected = reference_module.expected_results(self.spec)
        self.preset = reference_module.detection_preset(self.spec, self.mode)
        self.single = (
            reference_module.single_preset(self.spec, self.mode)
            if self.mode in ("reference", "taped")
            else None
        )

    def default_params(self) -> dict:
        """The pair's starting parameters: sample preset, then global defaults."""
        params = config.merge_params(self.preset)
        if self.spec and str(self.spec.get("sample")) in config.AHMED_SAMPLES:
            published = reference_module.ahmed_pair(
                str(self.spec.get("sample")), int(self.spec.get("index", 0) or 0)
            )
            if published:
                params["grid"]["rows"] = int(published.get("rows", 9))
                params["grid"]["cols"] = int(published.get("cols", 9))
        if self.mode in ("reference", "taped") and self.single:
            params["detection"]["sensitivity"] = 1.0
            if self.mode == "taped":
                params["detection"]["brightness_ratio"] = float(
                    self.single.get("taped_brightness_ratio", 1.5)
                )
        return params

    # -- keys and persistence -------------------------------------------------
    def _stage_key(self, params: dict) -> str:
        subset = {key: params[key] for key in config.STAGE_A_KEYS}
        return _hash(
            {
                "version": config.PIPELINE_VERSION,
                "seed": config.SEED,
                "mode": self.mode,
                "pair": [
                    (self.pair.get("reference") or {}).get("sha256"),
                    (self.pair.get("taped") or {}).get("sha256"),
                ],
                "stage_a": subset,
                "spec": self.spec,
                "preset": self.preset,
                "single": self.single,
            }
        )

    def _view_key(self, stage_key: str, params: dict) -> str:
        return _hash({"stage": stage_key, "display": params["display"]})

    def _state_path(self, stage_key: str) -> Path:
        return self.cache_dir / f"stage-{stage_key}.npz"

    def _state_meta_path(self, stage_key: str) -> Path:
        return self.cache_dir / f"stage-{stage_key}.json"

    def _stage_view_dir(self, view_key: str) -> Path:
        return config.RUNS / self.pair_id / f"stage-{view_key}"

    def _loss_view_dir(self, run_key: str) -> Path:
        return config.RUNS / self.pair_id / f"loss-{run_key}"

    def _state_from_npz(self, path: Path, meta: dict) -> dict:
        with np.load(path) as data:
            state = {
                "reference_warped": data["reference_warped"],
                "tape": data["tape"],
                "labels": data["labels"].astype(np.uint16),
                "boundary": data["boundary"].astype(bool),
                "scrape": data["scrape"].astype(bool),
                "old_foil": data["old_foil"].astype(bool),
                "valid": data["valid"].astype(bool),
                "delta": data["delta"],
                "brightness": data["brightness"],
                "field": data["field"],
                "matrix": data["matrix"],
            }
        state.update(
            {
                key: meta[key]
                for key in (
                    "registration",
                    "grid",
                    "noise",
                    "brightness_noise",
                    "field_coefficients",
                    "cell_ratio_residual_p95",
                    "valid_pixels",
                    "grid_pixels",
                    "scrape_pixels",
                    "oldfoil_pixels",
                    "core_pixels",
                    "mode",
                    "frame",
                    "eligible_supplied",
                )
                if key in meta
            }
        )
        return state

    def _save_state(self, state: dict, meta: dict, path: Path) -> None:
        np.savez_compressed(
            path,
            reference_warped=state["reference_warped"].astype(np.float32),
            tape=state["tape"].astype(np.float32),
            labels=state["labels"].astype(np.uint16),
            boundary=state["boundary"].astype(np.uint8),
            scrape=state["scrape"].astype(np.uint8),
            old_foil=state["old_foil"].astype(np.uint8),
            valid=state["valid"].astype(np.uint8),
            delta=state["delta"].astype(np.float32),
            brightness=state["brightness"].astype(np.float32),
            field=state["field"].astype(np.float32),
            matrix=np.asarray(state["matrix"], dtype=np.float64),
        )
        self._state_meta_path(path.stem.split("-", 1)[1]).write_text(
            json.dumps(_jsonable(meta), indent=2), encoding="utf-8"
        )

    def _load_state(self, stage_key: str) -> dict | None:
        path = self._state_path(stage_key)
        meta_path = self._state_meta_path(stage_key)
        if not path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return self._state_from_npz(path, meta)
        except Exception:
            return None

    # -- stage A --------------------------------------------------------------
    def ensure_state(self, params: dict, force: bool = False) -> tuple[dict, str]:
        stage_key = self._stage_key(params)
        state = None if force else self._load_state(stage_key)
        if state is not None:
            return state, stage_key

        spec = self.spec
        if self.mode == "paired":
            reference, ref_meta = read_gray(self.pair["reference"]["path"])
            taped, tape_meta = read_gray(self.pair["taped"]["path"])
            if reference.shape != taped.shape:
                original = reference.shape
                reference = np.asarray(
                    Image.fromarray(reference, mode="F").resize(
                        (taped.shape[1], taped.shape[0]), Image.Resampling.BILINEAR
                    ),
                    dtype=np.float32,
                )
                ref_meta["resized_from"] = list(original)
                ref_meta["resized_to"] = list(reference.shape)
                # Supplied grid coordinates only apply to their original frame.
                spec = None
            grid = grid_module.make_grid(reference, spec, params["grid"], taped.shape)
            state = segment.build_state(reference, taped, grid, params)
        else:
            key = "reference" if self.mode == "reference" else "taped"
            image, image_meta = read_gray(self.pair[key]["path"])
            # A supplied Ahmed grid is defined in the Taped frame.  A
            # Squared-only view uses automatic grid detection instead.
            grid_spec = spec if self.mode == "taped" else None
            grid = grid_module.make_grid(image, grid_spec, params["grid"], image.shape)
            state = segment.build_single_state(image, grid, params, self.mode)
            grid["info"]["frame"] = "taped" if self.mode == "taped" else "reference"
            ref_meta = image_meta if self.mode == "reference" else {}
            tape_meta = image_meta if self.mode == "taped" else {}
        state["grid"] = grid["info"]
        state["reference_meta"] = ref_meta
        state["tape_meta"] = tape_meta
        meta = {
            "pair": {
                "id": self.pair_id,
                "label": self.pair.get("label"),
                "reference": (self.pair.get("reference") or {}).get("name"),
                "taped": (self.pair.get("taped") or {}).get("name"),
                "reference_sha256": (self.pair.get("reference") or {}).get("sha256"),
                "taped_sha256": (self.pair.get("taped") or {}).get("sha256"),
            },
            "params": params,
            "seed": config.SEED,
            "version": config.PIPELINE_VERSION,
            "spec": spec,
            "expected": self.expected,
            "mode": self.mode,
            "frame": state.get("frame", "reference"),
            "eligible_supplied": state.get("eligible_supplied", False),
            "registration": state["registration"],
            "grid": state["grid"],
            "noise": state["noise"],
            "brightness_noise": state["brightness_noise"],
            "field_coefficients": state["field_coefficients"],
            "cell_ratio_residual_p95": state["cell_ratio_residual_p95"],
            "valid_pixels": state["valid_pixels"],
            "grid_pixels": state["grid_pixels"],
            "scrape_pixels": state["scrape_pixels"],
            "oldfoil_pixels": state["oldfoil_pixels"],
            "core_pixels": state["core_pixels"],
            "source_meta": {"reference": ref_meta, "taped": tape_meta},
        }
        self._save_state(state, meta, self._state_path(stage_key))
        state["__stage_meta__"] = meta
        return state, stage_key

    def ensure_stage_views(self, state: dict, params: dict, stage_key: str) -> list[dict]:
        view_key = self._view_key(stage_key, params)
        output_dir = self._stage_view_dir(view_key)
        marker = output_dir / "views.json"
        if marker.exists():
            try:
                return json.loads(marker.read_text(encoding="utf-8"))
            except Exception:
                pass
        thresholds = {
            "delta": max(0.22, params["detection"]["sigma_multiplier"] * state["noise"]) / max(0.1, params["detection"]["sensitivity"]),
            "brightness": np.log(params["detection"]["brightness_ratio"]) / max(0.1, params["detection"]["sensitivity"]),
        }
        if self.mode == "paired":
            views = render.render_stage(state, thresholds, output_dir, params["display"]["mode"])
        else:
            views = render.render_single_stage(
                state, thresholds, output_dir, self.mode, params["display"]["mode"]
            )
        marker.write_text(json.dumps(views, indent=2), encoding="utf-8")
        return views

    # -- stage B --------------------------------------------------------------
    def analyze(self, params: dict, force: bool = False) -> dict:
        merged = self.default_params()
        if params:
            for group, values in params.items():
                if group in merged and isinstance(values, dict):
                    merged[group].update(values)
        params = config.merge_params(merged)
        state, stage_key = self.ensure_state(params, force=force)
        stage_views = self.ensure_stage_views(state, params, stage_key)

        detection = params["detection"]
        run_key = _hash(
            {
                "stage": stage_key,
                "display": params["display"],
                "detection": detection,
            }
        )
        output_dir = self._loss_view_dir(run_key)
        result_json = output_dir / "result.json"
        if result_json.exists() and not force:
            try:
                cached = json.loads(result_json.read_text(encoding="utf-8"))
                cached["views"] = cached.get("views", [])
                cached["stage_views"] = stage_views
                cached["state"] = self._state_summary(state)
                cached["params"] = params
                cached["pair"] = self.pair
                cached["mode"] = self.mode
                cached["defaults"] = self.default_params()
                cached["preset"] = self.preset
                cached["single"] = self.single
                cached["expected"] = self.expected
                cached["hist"] = self._histograms(state, cached.get("thresholds", {}))
                self._write_last(cached)
                return cached
            except Exception:
                pass

        if self.mode == "paired":
            result = segment.detect(state, params)
            detection_views = render.render_detection(
                state, result, output_dir, params["display"]["mode"]
            )
        else:
            prior = None
            if self.mode == "reference" and self.single:
                prior = self.single.get("reference_prior_pct")
            result = segment.detect_single(state, params, self.mode, prior)
            detection_views = render.render_single_detection(
                state, result, output_dir, self.mode, params["display"]["mode"]
            )
        hist = self._histograms(state, result["thresholds"])
        cells = result["cells"]
        stats = result["stats"]
        expected = self.expected
        if expected:
            stats["reference_peeled_pct"] = expected.get("peeled_pct")
            stats["reference_retained_pct"] = expected.get("retained_pct")
            stats["reference_source"] = expected.get("source")
            if expected.get("peeled_pct") is not None:
                stats["reference_delta_pct"] = stats["peeled_pct"] - expected["peeled_pct"]
        payload = {
            "pair": self.pair,
            "mode": self.mode,
            "params": params,
            "defaults": self.default_params(),
            "preset": self.preset,
            "single": self.single,
            "seed": config.SEED,
            "version": config.PIPELINE_VERSION,
            "expected": expected,
            "state": self._state_summary(state),
            "stats": stats,
            "thresholds": result["thresholds"],
            "cells": cells,
            "hist": hist,
            "views": stage_views + detection_views,
            "stage_views": stage_views,
            "detection_views": detection_views,
            "run_key": run_key,
            "stage_key": stage_key,
        }
        result_json.write_text(json.dumps(_jsonable(payload), indent=2), encoding="utf-8")
        self._write_last(payload)
        return payload

    def _write_last(self, payload: dict) -> None:
        summary = {
            "run_key": payload.get("run_key"),
            "stage_key": payload.get("stage_key"),
            "mode": payload.get("mode", self.mode),
            "defaults": payload.get("defaults", self.default_params()),
            "preset": payload.get("preset", self.preset),
            "stats": payload.get("stats", {}),
            "thresholds": payload.get("thresholds", {}),
            "params": payload.get("params", {}),
            "pair": payload.get("pair", self.pair),
            "expected": payload.get("expected", self.expected),
            "cells": payload.get("cells", []),
            "seed": config.SEED,
            "version": config.PIPELINE_VERSION,
            "thumb": self._thumb_url(payload.get("detection_views", [])),
        }
        (self.cache_dir / "last.json").write_text(
            json.dumps(_jsonable(summary), indent=2), encoding="utf-8"
        )

    def _thumb_url(self, detection_views: list[dict]) -> str | None:
        for view in detection_views:
            if view.get("key") == "overlay":
                return view["url"].replace("overlay.png", "overlay_thumb.png")
        for view in detection_views:
            if view.get("key") == "status":
                return view["url"].replace("status.png", "status_thumb.png")
        return detection_views[0]["url"] if detection_views else None

    def _state_summary(self, state: dict) -> dict:
        registration = state.get("registration", {})
        return {
            "mode": state.get("mode", self.mode),
            "frame": state.get("frame", "reference"),
            "eligible_supplied": state.get("eligible_supplied", False),
            "registration": {
                "matrix": registration.get("matrix"),
                "matches": registration.get("match_count"),
                "inliers": registration.get("inliers"),
                "median_error_px": registration.get("median_error_px"),
                "p95_error_px": registration.get("p95_error_px"),
                "median_ncc": registration.get("median_ncc"),
                "warning": registration.get("warning"),
            },
            "grid": state.get("grid"),
            "noise": state.get("noise"),
            "brightness_noise": state.get("brightness_noise"),
            "field_coefficients": state.get("field_coefficients"),
            "cell_ratio_residual_p95": state.get("cell_ratio_residual_p95"),
            "valid_pixels": state.get("valid_pixels"),
            "grid_pixels": state.get("grid_pixels"),
            "scrape_pixels": state.get("scrape_pixels"),
            "oldfoil_pixels": state.get("oldfoil_pixels"),
        }

    def _histograms(self, state: dict, thresholds: dict) -> dict:
        delta = segment.histogram(state["delta"][state["valid"]], bins=110, limits=(-0.4, 0.8))
        brightness = segment.histogram(
            state["brightness"][state["valid"]], bins=110, limits=(-0.6, 1.25)
        )
        if thresholds:
            delta["threshold"] = thresholds.get("delta")
            brightness["threshold"] = thresholds.get("brightness")
        return {"mode": self.mode, "delta": delta, "brightness": brightness}


def get_pair_analysis(pair: dict) -> PairAnalysis:
    return PairAnalysis(pair)
