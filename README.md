# Adhesion

Deterministic web analysis of peeled coating area on foil.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Container and OpenShift

The included `Dockerfile` builds an OpenShift-compatible image on UBI 9 with
Python 3.12.  It listens on port **8080**, runs gunicorn, and follows the
arbitrary-UID model: application files and runtime directories are readable
and writable by supplementary group 0.

```bash
podman build -t adhesion .
podman run --rm -p 8080:8080 adhesion
```

For OpenShift, build this directory/repository with the Docker build strategy
(for example an `oc new-build --strategy=docker` BuildConfig), then deploy and
expose the resulting image.  The service should target port 8080.

`data/` is excluded from the build context and recreated at startup.  Mount a
persistent volume at `/opt/app-root/src/data` if uploads, manifests, caches and
rendered views must survive pod restarts; make sure OpenShift applies an
`fsGroup` (or otherwise grants group-0 write access) to that volume.  The raw
Ahmed TIFFs are not baked into the image; mount them at
`/opt/app-root/Ahmed_ThorCam_Raw_Images_TIFF` if the Validate page should run
the Ahmed checks inside the cluster.

The analysis keeps full-resolution float arrays in memory, so give the pod at
least 1 GiB (2 GiB recommended) and one CPU.  A single gunicorn worker is
intentional: the on-disk cache assumes one analysis writer at a time.

Drop as many images as you like. Files whose names contain
`Squared`/`Reference`/`Before` and `Taped`/`After`/`Peeled` are paired
automatically, including unequal counts: the app matches sample and view
numbers, pairs what it can, and keeps the leftovers as single-image
estimates. Files with no usable names fall back to upload order.

A single image is analysed too:

- **Taped only** — a screening estimate from locally bright, foil-like
  pixels. There is no before image, so this is a screening estimate rather
  than a measured peel. The brightness ratio is adjustable.
- **Squared only** — peeling cannot be observed without the taped view. For a
  recognised image the estimate is its published result (or sample mean) used
  as a database prior, clearly labelled; the image-derived bright-area screen
  is reported separately. For an unknown image the bright-area screen itself
  is shown, with a note that it is not a peel measurement.

Common image formats work directly (TIFF, PNG, JPEG, WebP, BMP, GIF, ...).
If Pillow cannot open a format, the app tries ImageMagick or ffmpeg. Reference
and taped images may have different dimensions; the reference is resized to
the taped frame before analysis.

Two demos are preloaded: **S13 demo** and **S16 demo**. They use inputs
reconstructed from the delivered display PNGs because the original raw TIFFs
are not present. Both demos run the same S13 calculation, so the S16 demo is
a worked example on an S16 pair rather than a reproduction of S16's own
published percentages.

## What the app does

The implementation follows the S13 paired-image pipeline:

1. **Align** — high-pass texture matching, robust affine fit of the Squared
   reference into Taped coordinates.
2. **Grid** — supplied Step-1 cell masks for matching reference hashes
   (including the Ahmed ThorCam taped-frame grids and analysis-domain masks),
   otherwise automatic cut-line detection and a row-major 9 x 9 cell grid.
   On automatically detected grids, the Grid view shows draggable cyan lines.
   Move any line that is off the real cut, then press **Apply grid**; **Reset**
   returns to automatic detection.  This works for paired and single images.
3. **Exclude** — original scrape bands, a registration safety margin,
   pre-existing bright foil candidates, and everything outside the grid.
4. **Normalise** — 0.6 px smoothing, a robust quadratic fit to paired
   log-intensity ratios, and a local brightness background.
5. **Detect** — component-filtered pixels above both the paired-change and
   local-brightness thresholds.

The default is the validated S13 V2 high-sensitivity setting:

```
sensitivity factor       5.0
paired threshold         max(0.22, 2.0 * sigma) / 5.0
brightness threshold     log(1.5) / 5.0
minimum component        3 pixels, 8-connected
```

The effective thresholds are measured from each image's own residual noise,
so each upload gets its own values. The UI exposes every stage's parameters
and redraws in real time. Display histogram equalisation is for viewing only;
measurements always use the 16-bit / native signal.

`Retained % = 100 - 100 * loss_pixels / eligible_pixels`.

The main retained/peeled numbers are shown with up to six decimal places.
Every adjustable parameter has a hover/focus tooltip.

## Ahmed ThorCam pairs

Exact raw Ahmed ThorCam TIFFs (S11, S12, S2, S5, S6) are recognised by
SHA-256. They use the supplied cell grids and analysis-domain masks, so
eligibility, excluded cells and denominators match the publication:

- S11 keeps its 9 x 8 layout and excluded cells 42, 52 and 53.
- S2, S5, S6 and S12 use their 9 x 9 grids and supplied eligible masks.

The five samples were published with different detectors, so each recognised
pair starts with a fixed per-sample preset (sensitivity, brightness ratio,
minimum component). These are ordinary sliders: the starting values reproduce
the published means, and you can adjust them live.

Bundled assets live in `adhesion/ahmed/` (`sources.json`, `grids/`,
`eligible/`). They only activate for the exact published images, never for a
resized or unrelated upload.

## Determinism

- Seed `1337` is fixed and recorded in every result.
- Linear-algebra thread counts are pinned to one before NumPy loads.
- No random sampling or stochastic optimisation is used.
- The analysis cache key contains both source SHA-256 hashes, every stage
  parameter, the pipeline version, and the seed.
- The same files and parameters therefore produce the same masks, cells and
  percentages on every run. The validation report checks byte-identical
  masks.

## Validation

The upload workflow does not display or score results against a reference.
The separate `Validate` page is a provenance check that the implementation
still reproduces the supplied S13 numbers and, when the raw files are present,
the five published Ahmed ThorCam samples.

`python3 -m adhesion.validate` regenerates `validation_report.json` and the
`Validate` page. The supplied folder does not contain the original S13/S16 raw
TIFFs, so the S13 checks use images reconstructed from the delivered 8-bit
`Green_Boundaries` PNGs. Ahmed checks read
`../Ahmed_ThorCam_Raw_Images_TIFF/` when it exists and compare every published
view, including eligible-pixel counts and repeat-run equality.

Latest Ahmed reproduction (default presets):

| Sample | Published mean | Implemented mean | Mean Δ |
|---|---|---|---|
| S11 | 1.1161 % | 1.1753 % | +0.059 pp |
| S12 | 0.2429 % | 0.2473 % | +0.004 pp |
| S2 | 0.9338 % | 0.9301 % | -0.004 pp |
| S5 | 14.4930 % | 14.5577 % | +0.065 pp |
| S6 | 3.4545 % | 3.4392 % | -0.015 pp |

Latest run (default parameters):

| Check | Result |
|---|---|
| S13 V2 reference mean | 17.42 % peeled |
| Implemented mean | 17.65 % peeled |
| Mean error | +0.23 pp |
| Per-view mask IoU | 0.855 – 0.889 |
| S16 independent mean | 15.25 % peeled |
| Difference from S16 | +2.40 pp (within 3 pp) |
| S18 independent mean | 16.77 % peeled |
| S13 V1 baseline | 1.29 % measured vs 1.26 % reference |
| Ahmed published views | 20 / 20 within 0.36 pp |
| Repeat masks identical | yes |

The S16/S18 files are independent analyses of a different specimen, so the
comparison is a plausibility band, not a pixel-level ground truth.

## Notes

- The 5.0x setting is intentionally high sensitivity. Blue marks are optical
  candidates, not confirmed bare aluminium.
- Four photos of one specimen are repeated views, not independent samples.
- Pairing prefers exact SHA-256 identities, then matching sample and view
  numbers in the filename. If counts differ, every image is still analysed:
  leftovers become Squared-only or Taped-only estimates.
- Different image dimensions are handled by resizing the reference to the
  taped frame. A supplied grid is skipped after a resize because its
  coordinates no longer apply.
- Runtime data lives in `data/`; caches may be deleted at any time.
- The **CSV** link under the filenames exports the summary and all per-cell rows.
- The two preloaded demos are S13 and S16; they are ordinary pairs and can be
  explored with the same sliders as an uploaded pair.

## Layout

```
app.py                  Flask routes
adhesion/               pipeline, registration, grid, rendering, validation
adhesion/ahmed/         bundled Ahmed grids, masks and published results
templates/              two minimal pages
static/                 vanilla JS and CSS
S13/, S16/              supplied reference material
validation_report.json  generated validation result
data/                   uploads, pair manifests, caches, rendered views
```
