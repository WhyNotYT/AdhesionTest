"""Flask entry point for the adhesion analysis web app."""
from __future__ import annotations

import os

# Deterministic linear-algebra kernels: fix reduction order before NumPy loads.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

import json
import csv
import io
import math

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

from adhesion import config, reference, store
from adhesion.io import pair_uploads, save_upload
from adhesion.pipeline import PairAnalysis

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 800 * 1024 * 1024
app.config["JSON_SORT_KEYS"] = False


def _validation_report() -> dict:
    path = config.ROOT / "validation_report.json"
    if not path.exists():
        return {"available": False}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        report["available"] = True
        return report
    except Exception:
        return {"available": False}


def _public_pair(pair: dict) -> dict:
    last = config.CACHE / pair["id"] / "last.json"
    summary = None
    if last.exists():
        try:
            payload = json.loads(last.read_text(encoding="utf-8"))
            thumb = payload.get("thumb")
            if thumb and thumb.startswith("/media/"):
                if not (config.RUNS / thumb[len("/media/"):]).exists():
                    thumb = None
            summary = {
                "stats": payload.get("stats", {}),
                "thresholds": payload.get("thresholds", {}),
                "thumb": thumb,
            }
        except Exception:
            summary = None
    reference_meta = pair.get("reference") or {}
    taped_meta = pair.get("taped") or {}
    mode = pair.get("mode", "paired")
    try:
        defaults = PairAnalysis(pair).default_params()
    except Exception:
        defaults = config.DEFAULTS
    return {
        "id": pair["id"],
        "label": pair.get("label", pair["id"]),
        "reference": reference_meta.get("name", ""),
        "taped": taped_meta.get("name", ""),
        "mode": mode,
        "estimated": mode != "paired",
        "demo": bool(
            (pair.get("reference_spec") or {}).get("demo")
            or reference_meta.get("demo")
            or taped_meta.get("demo")
        ),
        "reference_spec": pair.get("reference_spec"),
        "defaults": defaults,
        "summary": summary,
        "order": pair.get("order", 0),
    }


def _clean_json(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_json(item) for item in value]
    return value


@app.get("/")
def index():
    try:
        store.ensure_demo_pairs()
    except Exception:
        app.logger.exception("Could not prepare demo pairs")
    pairs = [_public_pair(pair) for pair in store.list_pairs()]
    payload = {
        "pairs": pairs,
        "defaults": config.DEFAULTS,
        "ranges": config.RANGES,
        "seed": config.SEED,
        "version": config.PIPELINE_VERSION,
    }
    return render_template("index.html", bootstrap=payload)


@app.get("/api/pairs")
def api_pairs():
    return jsonify(_clean_json({"pairs": [_public_pair(pair) for pair in store.list_pairs()]}))


@app.post("/api/upload")
def api_upload():
    files = request.files.getlist("files") or request.files.getlist("file")
    if not files:
        return jsonify({"error": "No files uploaded."}), 400
    saved = []
    try:
        for upload in files:
            if not upload or not upload.filename:
                continue
            saved.append(save_upload(upload, config.UPLOADS))
    except Exception as exc:
        return jsonify({"error": f"Could not read image: {exc}"}), 400
    if not saved:
        return jsonify({"error": "No usable files."}), 400

    pairs, singles, errors = pair_uploads(saved)
    created = []
    for item in pairs:
        reference_meta = item["reference"]
        taped_meta = item["taped"]
        identifier = store.pair_id(reference_meta["sha256"], taped_meta["sha256"])
        existing = store.get_pair(identifier)
        if existing:
            created.append(_public_pair(existing))
            continue
        spec = reference.lookup_reference(reference_meta["sha256"], taped_meta["sha256"])
        pair = {
            "id": identifier,
            "mode": "paired",
            "reference": reference_meta,
            "taped": taped_meta,
            "reference_spec": spec,
            "label": store._label(reference_meta["name"], taped_meta["name"]),
        }
        record = store.save_pair(pair)
        created.append(_public_pair(record))
    for item in singles:
        image = item["image"]
        mode = item["mode"]
        if mode == "reference":
            identifier = store.pair_id(image["sha256"], "")
            reference_meta, taped_meta = image, None
        else:
            identifier = store.pair_id("", image["sha256"])
            reference_meta, taped_meta = None, image
        existing = store.get_pair(identifier)
        if existing:
            created.append(_public_pair(existing))
            continue
        spec = reference.lookup_image(image["sha256"])
        suffix = "squared-only" if mode == "reference" else "taped-only"
        pair = {
            "id": identifier,
            "mode": mode,
            "reference": reference_meta,
            "taped": taped_meta,
            "reference_spec": spec,
            "label": f"{store._label(reference_meta['name'] if reference_meta else None, taped_meta['name'] if taped_meta else None)} · {suffix}",
        }
        record = store.save_pair(pair)
        created.append(_public_pair(record))
    if not created and errors:
        return jsonify({"error": " ".join(errors)}), 400
    return jsonify(_clean_json({"pairs": created, "singles": singles, "errors": errors}))


@app.post("/api/demo")
def api_demo():
    records = store.ensure_demo_pairs()
    return jsonify(_clean_json({"pairs": [_public_pair(record) for record in records]}))


@app.get("/api/pairs/<pair_id>")
def api_pair(pair_id: str):
    pair = store.get_pair(pair_id)
    if pair is None:
        return jsonify({"error": "Unknown pair."}), 404
    try:
        defaults = PairAnalysis(pair).default_params()
    except Exception:
        defaults = config.DEFAULTS
    return jsonify(_clean_json({"pair": _public_pair(pair), "defaults": defaults}))


@app.post("/api/pairs/<pair_id>/analyze")
def api_analyze(pair_id: str):
    pair = store.get_pair(pair_id)
    if pair is None:
        return jsonify({"error": "Unknown pair."}), 404
    body = request.get_json(silent=True) or {}
    params = body.get("params") or {}
    force = bool(body.get("force", False))
    try:
        analysis = PairAnalysis(pair)
        if not params:
            params = analysis.default_params()
        payload = analysis.analyze(params, force=force)
        payload["pair"] = _public_pair(pair)
        return jsonify(_clean_json(payload))
    except Exception as exc:
        app.logger.exception("Analysis failed")
        return jsonify({"error": str(exc)}), 500


@app.post("/api/pairs/<pair_id>/delete")
def api_delete_pair(pair_id: str):
    pair = store.get_pair(pair_id)
    if pair is None:
        return jsonify({"error": "Unknown pair."}), 404
    store.delete_pair(pair_id)
    return jsonify({"deleted": pair_id})


@app.get("/api/pairs/<pair_id>/results.csv")
def api_results_csv(pair_id: str):
    pair = store.get_pair(pair_id)
    if pair is None:
        return jsonify({"error": "Unknown pair."}), 404
    last_path = config.CACHE / pair_id / "last.json"
    payload = None
    if last_path.exists():
        try:
            payload = json.loads(last_path.read_text(encoding="utf-8"))
        except Exception:
            payload = None
    if payload is None or not payload.get("cells"):
        try:
            payload = PairAnalysis(pair).analyze({})
            cells = payload.get("cells", [])
            stats = payload.get("stats", {})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
    else:
        cells = payload.get("cells", [])
        stats = payload.get("stats", {})

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "image",
            "cell_id",
            "row",
            "column",
            "eligible_pixels",
            "loss_pixels",
            "retained_pixels",
            "loss_pct",
            "retained_pct",
            "status",
        ]
    )
    writer.writerow(
        [
            pair.get("label", pair_id),
            "ALL",
            "",
            "",
            stats.get("eligible_pixels"),
            stats.get("loss_pixels"),
            stats.get("retained_pixels"),
            stats.get("peeled_pct"),
            stats.get("retained_pct"),
            "summary",
        ]
    )
    for cell in cells:
        writer.writerow(
            [
                pair.get("label", pair_id),
                cell.get("cell_id"),
                cell.get("row"),
                cell.get("column"),
                cell.get("eligible_pixels"),
                cell.get("loss_pixels"),
                cell.get("retained_pixels"),
                cell.get("loss_pct"),
                cell.get("retained_pct"),
                cell.get("status"),
            ]
        )
    filename = "".join(character if character.isalnum() or character in "._-" else "_" for character in pair.get("label", "result"))
    response = Response(buffer.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}_results.csv"'
    return response


@app.get("/api/validation")
def api_validation():
    return jsonify(_clean_json(_validation_report()))


@app.get("/validation")
def validation_page():
    return render_template("validation.html", report=_validation_report(), bootstrap=None)


@app.get("/media/<path:filename>")
def media(filename: str):
    return send_from_directory(config.RUNS, filename, conditional=True)


@app.after_request
def cache_headers(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif request.path.startswith("/media/") and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
