"""Pair manifests and upload persistence."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import config
from .io import sha256_file


def pair_id(reference_sha: str, taped_sha: str) -> str:
    import hashlib

    return hashlib.sha256((reference_sha + ":" + taped_sha).encode("utf-8")).hexdigest()[:20]


def _manifest_path(pair: str) -> Path:
    return config.PAIRS / f"{pair}.json"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def _label(reference_name: str | None, taped_name: str | None) -> str:
    stem = Path(reference_name or taped_name or "image").stem
    match = re.search(r"(S\d+)", stem, re.IGNORECASE)
    index = re.findall(r"(?<![\d.])(\d+)(?![\d.])", stem)
    if match:
        return f"{match.group(1).upper()} {index[-1]}" if index else match.group(1).upper()
    return Path(reference_name or taped_name or "image").stem[:28]


def save_pair(pair: dict, order: int | None = None) -> dict:
    existing = get_pair(pair["id"])
    if existing is not None:
        return existing
    if order is None:
        order = next_order()
    record = dict(pair)
    record.setdefault(
        "label",
        _label(
            (record.get("reference") or {}).get("name"),
            (record.get("taped") or {}).get("name"),
        ),
    )
    record.setdefault("mode", "paired")
    record.setdefault("reference_spec", None)
    record["order"] = order
    _write_json(_manifest_path(record["id"]), record)
    return record


def next_order() -> int:
    orders = [int(pair.get("order", 0)) for pair in list_pairs(include_summary=False)]
    return (max(orders) + 1) if orders else 1


def get_pair(identifier: str) -> dict | None:
    path = _manifest_path(identifier)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def delete_pair(identifier: str) -> None:
    path = _manifest_path(identifier)
    if path.exists():
        path.unlink()


def list_pairs(include_summary: bool = True) -> list[dict]:
    pairs = []
    for path in config.PAIRS.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if include_summary:
            last_path = config.CACHE / record.get("id", "") / "last.json"
            if last_path.exists():
                try:
                    last = json.loads(last_path.read_text(encoding="utf-8"))
                    record["summary"] = {
                        "stats": last.get("stats", {}),
                        "thresholds": last.get("thresholds", {}),
                        "thumb": last.get("thumb"),
                        "expected": last.get("expected"),
                        "version": last.get("version"),
                        "seed": last.get("seed"),
                    }
                except Exception:
                    pass
        pairs.append(record)
    pairs.sort(
        key=lambda item: (
            1
            if (
                (item.get("reference_spec") or {}).get("demo")
                or (item.get("reference") or {}).get("demo")
                or (item.get("taped") or {}).get("demo")
            )
            else 0,
            int(item.get("order", 0)),
        )
    )
    return pairs


def existing_pair(reference_path: Path, taped_path: Path) -> dict | None:
    reference_sha = sha256_file(reference_path)
    taped_sha = sha256_file(taped_path)
    return get_pair(pair_id(reference_sha, taped_sha))


def ensure_demo_pairs() -> list[dict]:
    from .reference import s13_demo_pair, s16_demo_pair

    desired = [
        (101, s13_demo_pair(1, identifier="demo-s13", label="S13 demo")),
        (102, s16_demo_pair(1, identifier="demo-s16", label="S16 demo")),
    ]
    wanted_ids = {pair["id"] for _order, pair in desired}
    for path in config.PAIRS.glob("demo-*.json"):
        if path.stem not in wanted_ids:
            path.unlink(missing_ok=True)
    records = []
    for order, pair in desired:
        existing = get_pair(pair["id"])
        if existing is not None:
            # Demo inputs are reconstructed on demand, so their absolute paths
            # and hashes must follow the project when it is moved or mounted
            # somewhere else (for example inside a container).
            _manifest_path(pair["id"]).unlink(missing_ok=True)
        records.append(save_pair(pair, order=order))
    return records
