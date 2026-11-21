from pathlib import Path
import json,csv,hashlib
import numpy as np
from PIL import Image,ImageDraw,ImageFont

import os
ROOT=Path(os.environ.get('S16_WORK_DIR', Path.cwd()));ANA=ROOT/'analysis'
OUT=ROOT/'outputs'/'S16_Step2';OUT.mkdir(parents=True,exist_ok=True)
DATA=OUT/'Calculation_Masks';DATA.mkdir(exist_ok=True)
REFGRID=ROOT/'recovered'/'S16_Step1'/'Reusable_Grid_Data'
grid=json.loads((REFGRID/'S16_Step1_Grid_Definitions.json').read_text())
results=json.loads((ANA/'segmentation_results.json').read_text())
registration=json.loads((ANA/'registration_summary.json').read_text())
count_file=ANA/'independent_grid_counts.json'
if not count_file.exists():count_file=Path(__file__).resolve().parent/'independent_grid_counts.json'
counts=json.loads(count_file.read_text())
FONTPATH='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
FONT=ImageFont.truetype(FONTPATH,23);H1=ImageFont.truetype(FONTPATH,31);H2=ImageFont.truetype(FONTPATH,23);SMALL=ImageFont.truetype(FONTPATH,18)
GREEN=(25,245,65,255);YELLOW=(255,246,120,66);ORANGE=(255,157,60,67);RED=(255,75,70,80);BLUE=(90,205,255,172)

def transform(points,coeff):
    p=np.asarray(points,float);x=(p[:,0]-750)/500;y=(p[:,1]-540)/500
    return p+np.column_stack((np.ones(len(p)),x,y,x*x,x*y,y*y))@coeff

def draw_lines(draw,lines,color=GREEN,width=3):
    for line in lines:draw.line([tuple(p) for p in line],fill=color,width=width,joint='curve')

def composite(base,array):return Image.alpha_composite(base.convert('RGBA'),Image.fromarray(array)).convert('RGB')

reusable=[]
for result in results:
    i=result['image'];seg=np.load(ANA/f'segmentation_{i}.npz');labels=seg['labels'];eligible=seg['eligible'];loss=seg['loss'];grooves=seg['grooves']
    base=Image.open(ANA/f'taped_display_{i}.png').convert('RGB');gd=grid['images'][i-1]
    coeff=np.array(registration[i-1]['quadratic_displacement_coefficients'])
    hlines=[transform(line,coeff) for line in gd['horizontal_boundary_paths_px']]
    vlines=[transform(line,coeff) for line in gd['vertical_boundary_paths_px']]
    lines=hlines+vlines
    centres=[]
    for n in range(81):
        yy,xx=np.where(labels==n+1);centres.append((float(xx.mean()),float(yy.mean())))
    def numbered(im):
        dr=ImageDraw.Draw(im)
        for n,(x,y) in enumerate(centres):dr.text((round(x),round(y)),str(n),font=FONT,anchor='mm',fill='white',stroke_width=2,stroke_fill=(10,10,10))
        return im
    boundaries=base.copy();draw_lines(ImageDraw.Draw(boundaries),lines,color=GREEN[:3])
    boundaries.save(OUT/f'S16_Taped_{i}_Green_Boundaries.png')
    all_yellow=np.zeros((1080,1440,4),np.uint8);all_yellow[labels>0]=YELLOW
    yellow=composite(base,all_yellow);draw_lines(ImageDraw.Draw(yellow),lines,color=GREEN[:3])
    yellow.save(OUT/f'S16_Taped_{i}_Yellow_Cells.png')
    numbered(yellow.copy()).save(OUT/f'S16_Taped_{i}_Numbered_0-80.png')
    status=np.zeros((1080,1440,4),np.uint8)
    for cell in result['per_cell']:
        region=labels==cell['cell']+1
        color=RED if cell['status']=='Excluded' else (ORANGE if cell['status']=='Damaged' else YELLOW)
        status[region&eligible]=color
        if cell['status']=='Excluded':status[region]=color
    statuses=composite(base,status);draw_lines(ImageDraw.Draw(statuses),lines,color=GREEN[:3]);numbered(statuses)
    statuses.save(OUT/f'S16_Taped_{i}_Cell_Status.png')
    blue=np.zeros_like(status);blue[loss]=BLUE
    blue_image=composite(base,blue);draw_lines(ImageDraw.Draw(blue_image),lines,color=GREEN[:3])
    blue_image.save(OUT/f'S16_Taped_{i}_Blue_Loss.png')
    combined_overlay=Image.alpha_composite(Image.fromarray(status),Image.fromarray(blue))
    draw_lines(ImageDraw.Draw(combined_overlay),lines);numbered(combined_overlay)
    combined=Image.alpha_composite(base.convert('RGBA'),combined_overlay).convert('RGB')
    combined.save(OUT/f'S16_Taped_{i}_Combined_Overlay.png')
    combined_overlay.save(OUT/f'S16_Taped_{i}_Transparent_Combined_Overlay.png')
    # Actual aligned two-image overlay, with an equal image contribution.
    reg=np.load(ANA/f'registration_{i}.npz');refmat=reg['reference_intensity_matched']
    rawtape=np.asarray(Image.open(ROOT/'upload'/f'S16_Taped_[{i}].tif')).astype(float)
    lo,hi=np.percentile(rawtape,[.1,99.5])
    refshow=Image.fromarray(np.uint8(np.nan_to_num(np.clip((refmat-lo)/(hi-lo),0,1))**.8*255)).convert('RGB')
    aligned=Image.blend(refshow,base,.5);draw_lines(ImageDraw.Draw(aligned),lines,color=GREEN[:3]);numbered(aligned)
    aligned.save(OUT/f'S16_Taped_{i}_Squared_Taped_50-50_Aligned.png')
    # Side-by-side comparison, with original reference geometry warped to the taped frame.
    ref_annotated=refshow.copy();draw_lines(ImageDraw.Draw(ref_annotated),lines,color=GREEN[:3]);numbered(ref_annotated)
    pair=Image.new('RGB',(2920,1255),'#f5f6f5');pd=ImageDraw.Draw(pair)
    pd.text((20,16),f'S16 / Pair {i}  |  Squared reference aligned to Taped',font=H1,fill='#163529')
    pd.text((1480,16),f'Taped: estimated loss {result["loss_fraction"]:.2%} / retained {result["intact_fraction"]:.2%}',font=H1,fill='#163529')
    pair.paste(ref_annotated,(10,70));pair.paste(combined,(1470,70))
    legend=[('Green',(25,210,65),'cell boundary'),('Yellow',YELLOW[:3],'no detected loss'),('Orange',ORANGE[:3],'damaged cell'),('Red',RED[:3],'excluded cell'),('Blue',BLUE[:3],'estimated loss pixels')]
    x=25
    for name,color,meaning in legend:
        pd.rectangle((x,1173,x+27,1200),fill=color);pd.text((x+36,1175),f'{name}: {meaning}',font=SMALL,fill='#20372b');x+=560
    pd.text((25,1220),'Original scraped grooves are excluded. Dark new pits are treated as probable loss in this high-sensitivity estimate.',font=SMALL,fill='#334c40')
    pair.save(OUT/f'S16_Taped_{i}_Paired_Comparison.jpg',quality=94)
    for key,name in [('loss','Loss_Mask'),('strict_loss','Stricter_Loss_Mask'),('eligible','Eligible_AM_Mask'),('grooves','Excluded_Grooves_Mask'),('bright','Bright_Change_Mask'),('dark','Dark_Pit_Mask')]:
        Image.fromarray(seg[key].astype('uint8')*255).save(DATA/f'S16_Taped_{i}_{name}.png')
    Image.fromarray(labels.astype('uint16')).save(DATA/f'S16_Taped_{i}_Cell_IDs_1-81.png')
    boundaries_json={'image':i,'coordinate_frame':'original Taped image pixel coordinates, x rightward and y downward','source_squared':f'S16_Squared_[{i}].tif','source_taped':f'S16_Taped_[{i}].tif',
        'source_squared_sha256':hashlib.sha256((ROOT/'references'/f'S16_Squared_[{i}].tif').read_bytes()).hexdigest(),
        'source_taped_sha256':hashlib.sha256((ROOT/'upload'/f'S16_Taped_[{i}].tif').read_bytes()).hexdigest(),
        'horizontal_boundaries_px':[np.round(line,2).tolist() for line in hlines],
        'vertical_boundaries_px':[np.round(line,2).tolist() for line in vlines],
        'centroids_px':[list(np.round(c,2)) for c in centres],'registration':registration[i-1],'independent_grid_count':counts[i-1]}
    reusable.append(boundaries_json)

with (OUT/'S16_Step2_Summary.csv').open('w',newline='') as f:
    w=csv.writer(f);w.writerow(['Image','Columns','Rows','Total_cells','Intact_no_detected_loss','Damaged_cells','Excluded_cells','Eligible_AM_px','Peeled_AM_px','Retained_AM_px','Peeled_AM_percent','Retained_AM_percent','Stricter_loss_percent','Bright_change_percent','Dark_pit_percent'])
    for r in results:w.writerow([f'S16_Taped_[{r["image"]}]',r['columns'],r['rows'],r['total_cells'],r['no_detected_loss_cells'],r['damaged_cells'],r['excluded_cells'],r['eligible_am_px'],r['loss_px'],r['intact_px'],r['loss_fraction']*100,r['intact_fraction']*100,r['strict_loss_fraction']*100,r['bright_loss_fraction']*100,r['dark_pit_loss_fraction']*100])
with (OUT/'S16_Step2_Per_Cell.csv').open('w',newline='') as f:
    w=csv.writer(f);w.writerow(['Image','Cell_0based','Row_1based','Column_1based','Status','Total_cell_px','Excluded_groove_px','Eligible_AM_px','Loss_px','Retained_AM_px','Loss_percent','Retained_percent','Stricter_loss_px','Bright_change_px','Dark_pit_px'])
    for r in results:
        for c in r['per_cell']:w.writerow([r['image'],c['cell'],c['row'],c['column'],c['status'],c['total_cell_px'],c['groove_excluded_px'],c['eligible_am_px'],c['loss_px'],c['intact_px'],100*c['loss_fraction'],100*(1-c['loss_fraction']),c['strict_loss_px'],c['bright_loss_px'],c['dark_pit_loss_px']])

count_text='S16 - STEP 2: INDEPENDENT GRID COUNTS\n'+'='*62+'\n\n'
count_text+='Image                  Columns (horizontal)   Rows (vertical)   Total   Numbering\n'
for r in results:count_text+=f'S16_Taped_[{r["image"]}].tif     9                      9                 81      0-80\n'
count_text+='''
Counting basis: each Taped image was inspected separately, with independent
cut-contrast projection checks. Ten vertical and ten horizontal cuts enclose
nine columns and nine rows. The broader outside coating margins and cut
extensions beyond the enclosed grid are not counted as cells.

Numbering starts at the upper-left enclosed cell: 0-8 on the first row,
9-17 on the next, continuing to 72-80 on the bottom row.

All Taped outputs use the original 1440 x 1080 pixel coordinate frame.
Reference images were registered separately to their matching Taped images;
the curved cut paths were transferred into the Taped coordinate frame.
The images show the same physical sample; do not sum the counts as if they
were four independent 81-cell specimens.
'''
(OUT/'S16_Step2_Cell_Counts.txt').write_text(count_text)

mean_loss=float(np.mean([r['loss_fraction'] for r in results]));mean_strict=float(np.mean([r['strict_loss_fraction'] for r in results]));mean_bright=float(np.mean([r['bright_loss_fraction'] for r in results]))
summary='S16 - STEP 2: HIGH-SENSITIVITY IMAGE-AREA ESTIMATE\n'+'='*74+'\n\n'
summary+='Image     Grid   Total   Intact*  Damaged  Excluded  Retained AM %  Peeled AM %\n'
for r in results:summary+=f'{r["image"]:<9}9x9    81      {r["no_detected_loss_cells"]:<8}{r["damaged_cells"]:<9}{r["excluded_cells"]:<10}{r["intact_fraction"]*100:>8.2f}       {r["loss_fraction"]*100:>7.2f}\n'
summary+=f'\nFour-photo arithmetic mean: retained AM {100*(1-mean_loss):.2f}%; estimated peeled AM {100*mean_loss:.2f}%.\n'
summary+='''
* Intact cell means no loss pixels were detected under the stated criteria.
All 81 cells show some detected change consistent with removal in each view.
No whole cells are excluded. Original scraped groove pixels are excluded
within the cells; this does not make a whole cell an excluded cell.

Loss % = 100 x detected loss pixels / eligible original AM pixels.
Retained % = 100 - Loss %.
Eligible original AM pixels are inside the enclosed grid after removing
the registered pre-tape scraped-groove mask. The same eligible-pixel
denominator is used for both percentages. These are area ratios, not the
fraction of cells classified as damaged.

Interpretation: the main result is a high-sensitivity estimate. It includes
new bright areas and new dark pits absent from the aligned reference. Dark
pits are treated as probable coating loss. Grayscale photographs alone do
not establish that every dark pit exposes Al rather than changed texture,
shadow, displaced coating, or surface damage. The main result should not be
reported as independently confirmed bare-Al area or adhesion force.
'''
summary+=f'\nDetection-threshold comparison: mean loss {mean_strict*100:.2f}% with stricter criteria versus {mean_loss*100:.2f}% with the main criteria.\n'
summary+=f'Bright-change subset only: mean {mean_bright*100:.2f}% of eligible AM area. This is a diagnostic subset, not a validated true-loss bound.\n'
summary+='''The threshold comparison is not a confidence interval. The four photos
depict one specimen and are not independent experimental replicates.

COLOR KEY
Green: curved cell boundaries.
Light transparent yellow: cells with no detected loss; also used in the
    separate Yellow_Cells view to show every identified cell.
Transparent orange: a cell containing one or more retained loss components.
Transparent red: whole cells excluded from analysis (none here).
Light blue: exactly the estimated loss-pixel set used in the main calculation.
Original grooves are left uncolored in the combined loss calculation view.

The binary masks are authoritative for pixel counts. Text labels and green
boundaries in presentation images can obscure a few blue pixels visually;
the loss mask preserves the full calculation set without text or lines.

FILES
For each of four views: Green_Boundaries, Yellow_Cells, Numbered_0-80,
Cell_Status, Blue_Loss, Combined_Overlay, Transparent_Combined_Overlay,
Squared_Taped_50-50_Aligned and Paired_Comparison.
Separate count TXT, summary TXT/CSV, per-cell CSV and an Excel workbook.
Calculation_Masks contains loss, eligible-AM and excluded-groove masks,
the stricter threshold result, bright/dark diagnostic masks, cell labels,
and curved boundary/registration definitions.
'''
(OUT/'S16_Step2_Results_and_Method.txt').write_text(summary)
parameters={'sample':'S16','analysis':'high-sensitivity paired image-area estimate','summary_mean_loss_fraction':mean_loss,'summary_mean_retained_fraction':1-mean_loss,
    'photo_mean_stricter_loss_fraction':mean_strict,'photo_mean_bright_change_fraction':mean_bright,
    'methods':{'grid_count':'independent cut-contrast projections and visual checks in Taped images','registration':'robust local normalized texture matching followed by a quadratic geometric correction; each Squared is resampled to its Taped counterpart',
        'original_groove_exclusion':{'centreline_core_radius_px':2.2,'adjacent_original_cut_corridor_radius_px':10,'dark_relative_contrast':.40,'bright_relative_contrast':.65,'dilation_px':1,'connected_strong_original_spall_radius_px':18},
        'photometry':'robust global reference-to-Taped intensity matching followed by a smooth locally fitted illumination residual (Gaussian sigma 35 px)',
        'main_detection':{'dark_seed_z_below':-3.1,'dark_seed_intensity_below_fraction_of_local_AM':.79,'dark_growth_z_below':-1.85,'dark_growth_intensity_below_fraction_of_local_AM':.90,'bright_seed_z_above':3.8,'bright_seed_intensity_above_fraction_of_local_AM':1.34,'bright_growth_z_above':2.,'bright_growth_intensity_above_fraction_of_local_AM':1.16,'minimum_connected_component_px':5,'maximum_filled_enclosed_hole_px':30},
        'stricter_detection':{'dark_seed_z_below':-4.,'dark_seed_intensity_below_fraction_of_local_AM':.72,'dark_growth_z_below':-2.6,'dark_growth_intensity_below_fraction_of_local_AM':.85,'bright_seed_z_above':4.8,'bright_seed_intensity_above_fraction_of_local_AM':1.5,'bright_growth_z_above':2.8,'bright_growth_intensity_above_fraction_of_local_AM':1.25,'minimum_connected_component_px':7},
        'limitation':'new dark pits are probable coating loss, not independently confirmed exposed Al; repeated illumination views do not establish accuracy'},
    'binary_mask_encoding':'8-bit masks: 255=included, 0=not included. Cell labels: 0=outside; 1-81 represent displayed cell IDs 0-80.',
    'geometry':reusable,'image_results':results}
(DATA/'S16_Step2_Analysis_Definitions.json').write_text(json.dumps(parameters,indent=2)+'\n')

# A compact review sheet at full legibility, independent of calculation images.
overview=Image.new('RGB',(1960,1690),'#f5f7f6');od=ImageDraw.Draw(overview)
od.text((25,18),'S16 / Step 2 / High-sensitivity estimated AM loss',font=H1,fill='#193b2c')
od.text((25,63),f'Photo mean: {100*mean_loss:.1f}% loss  |  {100*(1-mean_loss):.1f}% retained  |  81 cells per image',font=H2,fill='#294b3a')
for j,r in enumerate(results):
    x=20+(j%2)*970;y=112+(j//2)*760
    od.text((x+10,y),f'Image {r["image"]}  |  loss {100*r["loss_fraction"]:.2f}%  |  retained {100*r["intact_fraction"]:.2f}%',font=H2,fill='#234532')
    v=Image.open(OUT/f'S16_Taped_{r["image"]}_Combined_Overlay.png');v.thumbnail((940,705),Image.Resampling.LANCZOS);overview.paste(v,(x+10,y+35))
od.text((30,1650),'Blue = estimated loss pixels. Orange = damaged cell. Dark new pits are included as probable loss.',font=SMALL,fill='#344f40')
overview.save(OUT/'S16_Step2_Combined_Overview.jpg',quality=94)
print(json.dumps({'output_directory':str(OUT),'mean_loss_percent':mean_loss*100,'mean_retained_percent':(1-mean_loss)*100,'mean_stricter_loss_percent':mean_strict*100,'image_file_count':len(list(OUT.glob('*.png')))}))
