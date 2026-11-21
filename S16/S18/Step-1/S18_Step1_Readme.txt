S18 STEP 1 - FILE GUIDE

For each of the four source photographs:
  S18_Squared_N_Green_Boundaries.png : source display with green groove boundaries.
  S18_Squared_N_Yellow_Cells.png : transparent light-yellow cells with green boundaries.
  S18_Squared_N_Numbered_0-80.png : cell IDs 0-80 on the yellow-and-green version.

Additional reusable annotations, all in original 1440 x 1080 pixel coordinates:
  S18_Squared_N_Transparent_Overlay.png : RGBA yellow-and-green layer without a photographic background.
  S18_Squared_N_Cell_ID_Mask.tif : integer label image; 0 = outside grid, 1-81 = printed IDs 0-80.
  S18_Squared_N_Cell_Geometry.json : individually traced polygons, centres, intersections, and display-window values.

S18_Step1_Cell_Counts.txt is the requested separate count table and counting notes.
S18_Step1_Numbered_Overview.jpg is a reduced four-image preview. Use the individual PNGs for full-size inspection.

All four inputs show the same grid in the same orientation. Each input has its own traced annotation. No geometric resampling was applied to individual outputs. Coordinate origin is the upper-left image corner; x increases rightward and y increases downward.

The source TIFF files have not been modified. Their SHA-256 hashes are recorded in the corresponding geometry files. PNG background brightness uses a linear display window, recorded in each geometry file. These viewing images are not replacements for raw intensity data.

The mask files identify cells, including their boundary pixels; they are not material-loss masks. Detached one- or two-pixel polygon rasterization fragments were assigned to the nearest stable neighbouring cell. Step 1 does not calculate adhesion loss or classify damaged cells.
