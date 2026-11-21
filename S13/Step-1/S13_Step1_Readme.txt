S13 STEP-1 DELIVERABLES

For each of the four source images:
* Green_Boundaries.png: green cut centerlines and the outer grid perimeter.
* Yellow_Cells.png: the same green boundaries plus a 23% light-yellow fill.
* Numbered_0-80.png: the green/yellow overlay with individual cell numbers.

All annotated images are lossless RGB PNG files at the original 1440 x 1080
pixel dimensions. Background display mapping is sqrt(raw/1023)*255, rounded
to 8-bit, using one fixed mapping for all four 10-bit-range TIFF inputs. This
preserves brightness order without clipping the bright exposed substrate.
It is a display conversion, not an image used for later pixel-loss measurement.
The original uploaded TIFFs are not modified.

Green = RGB (0,230,60), 3 pixels wide. Yellow = RGB (255,245,150), alpha 23%.
Small translucent pale patches improve the readability of the black cell IDs.

Reusable_Grid_Data contains source-coordinate data for later paired analysis:
* Transparent_Overlay.png: exact RGBA overlay, with no background image.
* Cell_ID_Mask.tif: lossless 16-bit cell labels. 0 is OUTSIDE; mask values 1..81
  correspond to displayed IDs 0..80, respectively. Thus cell 0 is mask value 1.
* Boundary_Mask.png: 255 at the drawn green boundaries, 0 elsewhere.
* S13_Grid_Geometry.json: per-image cut intersections, curved cell polygons,
  centroids, pixel areas, source hashes, orientation and numbering conventions.
* S13_Cell_Locations.csv: tabular cell IDs, positions and pixel areas.

Geometry is traced independently for each exposure. Faint/absent cut segments
are connected by interpolation. In particular, the fourth vertical cut is
weak and partly inferred. These masks are reviewable annotations rather than
ground-truth measurements of invisible edges. Register subsequent taped views
to their corresponding original TIFF before transferring the grid.

There are 81 physical cells viewed four times, not 324 independent specimens.
Step 1 does not classify adhesion loss or retention.
