S16 Step-2 analysis source snapshot

The Python scripts preserve the methods used for this estimate. They require
NumPy, SciPy and Pillow and the original source data. Set S16_WORK_DIR to an
analysis workspace containing:
  references/S16_Squared_[1..4].tif
  upload/S16_Taped_[1..4].tif
  recovered/S16_Step1/Reusable_Grid_Data/ (from the Step-1 ZIP)

Run register_s16.py, segment_s16.py, then render_s16_results.py. Registration
creates the display PNGs needed downstream. The independent grid-projection
counts JSON is included here and is used as the fallback count record.

The optional workbook builder uses the @oai/artifact-tool JavaScript package
in the Codex primary runtime. It reads the same analysis JSON outputs.

The final masks and analysis definitions JSON preserve all reported area
ratios without requiring a rerun. Binary masks are authoritative: 255 means
included, 0 means not included. Cell-label mask IDs 1-81 correspond to the
displayed cell numbers 0-80, while 0 denotes outside the grid.

Threshold changes require rerunning segmentation and regenerating every
summary and overlay from the updated masks. Multiplying a reported loss
percentage is not equivalent to increasing detection sensitivity.
