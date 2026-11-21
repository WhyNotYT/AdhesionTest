"""Image and upload helpers."""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 120_000_000

REF_WORDS = ("squared", "reference", "before", "unpeeled", "control", "intact")
TAPE_WORDS = ("taped", "tape", "after", "peeled", "peel")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def natural_key(text: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def _to_luma(array: np.ndarray) -> np.ndarray:
    if array.ndim == 2:
        return array.astype(np.float32, copy=False)
    if array.ndim == 3 and array.shape[2] >= 3:
        rgb = array[..., :3].astype(np.float32, copy=False)
        return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114
    if array.ndim == 3 and array.shape[2] == 1:
        return array[..., 0].astype(np.float32, copy=False)
    raise ValueError("Unsupported image shape")


def read_gray(path: str | Path) -> tuple[np.ndarray, dict]:
    """Read an image as float32 luminance, normalised to a ~10-bit white level.

    The calculation uses ratios.  The scale only matters for the two absolute
    floors (the log floor and the pre-existing bright foil test), so normalising
    to the same level as the original 10-bit TIFF containers keeps the audited
    constants meaningful for 8-bit uploads too.
    """
    path = Path(path)
    image = ImageOps.exif_transpose(Image.open(path))
    image.load()
    mode = image.mode
    if mode in {"P", "CMYK", "YCbCr", "LAB", "HSV"}:
        image = image.convert("RGB")
    elif mode == "1":
        image = image.convert("L")
    elif mode in {"LA", "RGBA", "RGBa", "La"}:
        image = image.convert("RGBA")
    raw = np.array(image)
    dtype = raw.dtype
    raw = _to_luma(raw)
    finite = raw[np.isfinite(raw)]
    if finite.size == 0:
        raise ValueError(f"Empty image: {path.name}")

    if dtype == np.uint8:
        scale = 255.0
    elif dtype == np.uint16:
        high = float(np.percentile(finite, 99.9))
        scale = 1023.0 if high <= 1023.0 else max(high, 1.0)
    elif dtype == np.float32 or dtype == np.float64:
        high = float(np.percentile(finite, 99.9))
        scale = 1.0 if high <= 1.0 else max(high, 1.0)
    else:
        high = float(np.percentile(finite, 99.9))
        scale = 255.0 if high <= 255.0 else (1023.0 if high <= 1023.0 else max(high, 1.0))

    array = np.maximum(raw, 0.0) / scale
    meta = {
        "path": str(path),
        "name": path.name,
        "mode": mode,
        "dtype": str(dtype),
        "shape": list(array.shape),
        "scale": scale,
        "minimum": float(np.min(array)),
        "maximum": float(np.max(array)),
        "median": float(np.median(array)),
        "p99": float(np.percentile(array, 99.0)),
    }
    return array.astype(np.float32), meta


def classify_upload(name: str) -> str | None:
    lowered = name.lower()
    # Check the peeled/taped words first: "unpeeled" contains "peel".
    if "unpeeled" in lowered or "squared" in lowered or "reference" in lowered:
        return "reference"
    if any(word in lowered for word in TAPE_WORDS):
        return "taped"
    if any(word in lowered for word in REF_WORDS):
        return "reference"
    return None


def _index_key(name: str) -> str:
    matches = re.findall(r"(?<![\d.])(\d+)(?![\d.])", Path(name).stem)
    return matches[-1] if matches else ""


GENERIC_TOKENS = {
    "squared", "square", "reference", "before", "unpeeled", "control", "intact",
    "taped", "tape", "after", "peeled", "peel", "image", "img", "photo",
    "raw", "copy", "scan", "view", "tif", "tiff", "png", "jpg", "jpeg",
}


def _tokens(name: str) -> set[str]:
    parts = re.findall(r"[a-z0-9]+", Path(name).stem.lower())
    return {part for part in parts if part not in GENERIC_TOKENS and not part.isdigit()}


def _sample_token(name: str) -> str:
    match = re.search(r"(S\d+)", Path(name).stem, re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _known(sha: str) -> dict | None:
    from . import reference

    return reference.lookup_image(sha)


def _pair_score(reference: dict, taped: dict, ref_pos: int, tape_pos: int) -> float:
    ref_known = _known(reference.get("sha256", ""))
    tape_known = _known(taped.get("sha256", ""))
    if ref_known and tape_known:
        if (
            ref_known.get("sample") == tape_known.get("sample")
            and int(ref_known.get("index", 0)) == int(tape_known.get("index", 0))
        ):
            return 1000.0
        if ref_known.get("sample") == tape_known.get("sample"):
            difference = abs(int(ref_known.get("index", 0)) - int(tape_known.get("index", 0)))
            return 300.0 - 10.0 * difference
        return -100.0

    ref_sample = _sample_token(reference["name"])
    tape_sample = _sample_token(taped["name"])
    ref_index = _index_key(reference["name"])
    tape_index = _index_key(taped["name"])
    score = 0.0
    if ref_sample and tape_sample:
        score += 200.0 if ref_sample == tape_sample else -200.0
    if ref_index and tape_index:
        score += 120.0 if ref_index == tape_index else -60.0
    if ref_sample and tape_sample and ref_sample == tape_sample:
        score += 10.0 * len(_tokens(reference["name"]) & _tokens(taped["name"]))
    if ref_known and tape_sample and ref_known.get("sample") == tape_sample:
        score += 100.0
    if tape_known and ref_sample and tape_known.get("sample") == ref_sample:
        score += 100.0
    score += max(0.0, 10.0 - abs(ref_pos - tape_pos))
    return score


def _assign_pairs(refs: list[dict], tapes: list[dict], min_score: float) -> list[tuple[dict, dict, float]]:
    if not refs or not tapes:
        return []
    try:
        from scipy.optimize import linear_sum_assignment

        size = max(len(refs), len(tapes))
        scores = np.zeros((size, size), dtype=float)
        for r, reference in enumerate(refs):
            for t, taped in enumerate(tapes):
                scores[r, t] = _pair_score(reference, taped, r, t)
        rows, columns = linear_sum_assignment(-scores)
        candidates = [
            (refs[r], tapes[c], float(scores[r, c]))
            for r, c in zip(rows, columns)
            if r < len(refs) and c < len(tapes) and scores[r, c] >= min_score
        ]
    except Exception:
        candidates = []
        for r, reference in enumerate(refs):
            for t, taped in enumerate(tapes):
                score = _pair_score(reference, taped, r, t)
                if score >= min_score:
                    candidates.append((reference, taped, score))
        candidates.sort(key=lambda item: -item[2])
        used_refs: set[str] = set()
        used_tapes: set[str] = set()
        filtered = []
        for reference, taped, score in candidates:
            if reference["sha256"] in used_refs or taped["sha256"] in used_tapes:
                continue
            used_refs.add(reference["sha256"])
            used_tapes.add(taped["sha256"])
            filtered.append((reference, taped, score))
        candidates = filtered
    candidates.sort(key=lambda item: (natural_key(_index_key(item[0]["name"])), natural_key(item[0]["name"])))
    return candidates


def _single(mode: str, item: dict) -> dict:
    return {"mode": mode, "image": item, "index": _index_key(item["name"])}


def pair_uploads(items: Iterable[dict]) -> tuple[list[dict], list[dict], list[str]]:
    """Pair many uploads, or keep single images for screening estimates.

    Filename sample/index tokens and published SHA-256 identities drive a
    global assignment.  Leftover images become single-image estimates instead
    of causing the whole upload to fail.
    """
    items = list(items)
    if not items:
        return [], [], ["No images uploaded."]

    # The same file can be dropped twice; keep the first occurrence only.
    unique: list[dict] = []
    seen: set[str] = set()
    for item in items:
        digest = item.get("sha256", "")
        if digest and digest in seen:
            continue
        if digest:
            seen.add(digest)
        unique.append(item)
    items = unique

    refs, tapes, unknown = [], [], []
    for item in items:
        kind = classify_upload(item["name"])
        if kind == "reference":
            refs.append(item)
        elif kind == "taped":
            tapes.append(item)
        else:
            unknown.append(item)

    if not refs and not tapes:
        # No usable names: keep the historical reference/taped upload order.
        refs = items[0::2]
        tapes = items[1::2]
        if len(refs) > len(tapes):
            return (
                [
                    {"reference": reference, "taped": taped, "index": _index_key(reference["name"]) or _index_key(taped["name"])}
                    for reference, taped in zip(refs, tapes)
                ],
                [_single("reference", refs[-1])],
                ["No Squared/Taped names found: paired in upload order; the last image is a single-image estimate."],
            )
        return (
            [
                {"reference": reference, "taped": taped, "index": _index_key(reference["name"]) or _index_key(taped["name"])}
                for reference, taped in zip(refs, tapes)
            ],
            [],
            ["No Squared/Taped names found: paired in upload order."],
        )

    # Let unclassified files complete the smaller side when the counts fit.
    if refs and not tapes and unknown:
        tapes, unknown = unknown, []
    elif tapes and not refs and unknown:
        refs, unknown = unknown, []
    elif refs and tapes and unknown:
        if len(refs) + len(unknown) == len(tapes):
            refs, unknown = refs + unknown, []
        elif len(tapes) + len(unknown) == len(refs):
            tapes, unknown = tapes + unknown, []

    refs.sort(key=lambda row: (natural_key(_index_key(row["name"])), natural_key(row["name"])))
    tapes.sort(key=lambda row: (natural_key(_index_key(row["name"])), natural_key(row["name"])))

    if refs and tapes:
        probe = max(_pair_score(reference, taped, 0, 0) for reference in refs for taped in tapes)
        min_score = 50.0 if probe > 10.0 else 0.0
        matches = _assign_pairs(refs, tapes, min_score)
    else:
        matches = []

    pairs = [
        {
            "reference": reference,
            "taped": taped,
            "index": _index_key(reference["name"]) or _index_key(taped["name"]),
        }
        for reference, taped, _score in matches
    ]
    paired_refs = {reference["sha256"] for reference, _taped, _score in matches}
    paired_tapes = {taped["sha256"] for _reference, taped, _score in matches}

    notes: list[str] = []
    singles: list[dict] = []
    for item in refs:
        if item["sha256"] not in paired_refs:
            singles.append(_single("reference", item))
    for item in tapes:
        if item["sha256"] not in paired_tapes:
            singles.append(_single("taped", item))
    for item in unknown:
        singles.append(_single("reference", item))

    if not pairs and not singles:
        return [], [], ["No usable images."]
    return pairs, singles, notes

def _external_convert(source: Path, destination: Path) -> Path | None:
    """Best-effort conversion for formats Pillow cannot open (HEIC, RAW, ...)."""
    commands = []
    magick = shutil.which("magick")
    convert = shutil.which("convert")
    if magick:
        commands.append([magick, f"{source}[0]", "-auto-orient", "-depth", "16", str(destination)])
    elif convert:
        commands.append([convert, f"{source}[0]", "-auto-orient", "-depth", "16", str(destination)])
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        commands.append(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-pix_fmt",
                "gray16le",
                str(destination),
            ]
        )
    for command in commands:
        destination.unlink(missing_ok=True)
        try:
            result = subprocess.run(command, capture_output=True, timeout=60, text=True)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and destination.exists() and destination.stat().st_size > 0:
            return destination
    return None


def save_upload(source, destination_dir: Path) -> dict:
    """Persist a Werkzeug FileStorage by content hash and return metadata."""
    name = Path(source.filename or "image").name
    temp = destination_dir / (".upload-" + hashlib.sha256(name.encode()).hexdigest()[:10])
    source.save(temp)
    digest = sha256_file(temp)
    suffix = Path(name).suffix.lower() or ".img"
    final = destination_dir / f"{digest}{suffix}"
    if final.exists():
        temp.unlink(missing_ok=True)
    else:
        shutil.move(str(temp), str(final))

    converted = False
    try:
        image, meta = read_gray(final)
    except Exception:
        destination = destination_dir / f"{digest}_converted.tif"
        converted_path = _external_convert(final, destination)
        if converted_path is None:
            raise ValueError(
                f"Could not read {name}. Use a common image format (TIFF, PNG, JPEG, WebP, BMP, GIF)."
            )
        final = converted_path
        image, meta = read_gray(final)
        converted = True

    meta["original_name"] = name
    meta["converted"] = converted
    return {
        "name": name,
        "path": str(final),
        "sha256": digest,
        "width": int(image.shape[1]),
        "height": int(image.shape[0]),
        "meta": meta,
    }
