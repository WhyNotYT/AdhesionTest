from pathlib import Path
import csv, hashlib, json, textwrap
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi
from s13_register import ROOT, WORK, display, read_raw, transform_xy

OUT=ROOT/'S13_Step2'
OUT.mkdir(exist_ok=True)
DATA=OUT/'Reusable_Data';DATA.mkdir(exist_ok=True)
FONT=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',17)
SMALL=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',15)
LARGE=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',25)
GREEN=np.array([0,230,60]);YELLOW=np.array([255,245,150]);ORANGE=np.array([255,165,65]);RED=np.array([255,90,90]);BLUE=np.array([100,205,255])

def tint(array, mask, color, alpha):
    array[mask]=np.uint8(np.rint((1-alpha)*array[mask]+alpha*color))

def save(array,name):
    Image.fromarray(array).save(OUT/name)

def numbered(array,cells):
    image=Image.fromarray(array);draw=ImageDraw.Draw(image,'RGBA')
    for cell in cells:
        x,y=cell['centroid_xy'];text=str(cell['cell_id'])
        box=draw.textbbox((x,y),text,font=FONT,anchor='mm',stroke_width=0)
        draw.rounded_rectangle((box[0]-3,box[1]-2,box[2]+3,box[3]+2),radius=3,fill=(255,255,225,140))
        draw.text((x,y),text,font=FONT,anchor='mm',fill=(0,0,0,255))
    return np.array(image)

def write_csv(path,rows):
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def main():
    geom=json.loads((ROOT/'S13_Step1/Reusable_Grid_Data/S13_Grid_Geometry.json').read_text())
    seg_stats=json.loads((WORK/'S13_Segmentation_Diagnostics.json').read_text())
    reg_stats=json.loads((WORK/'S13_Registration_Diagnostics.json').read_text())
    sourcehashes=[];summaries=[];allcells=[];sweeps=[];tapedgeometry=[]
    for i in range(1,5):
        data=np.load(WORK/f'S13_Segmentation_{i}.npz');reg=np.load(WORK/f'S13_Registration_{i}.npz')
        t=read_raw('Taped',i);labels=data['labels'];loss=data['loss'];valid=data['valid'];scrape=data['scrape'];oldfoil=data['oldfoil']
        grid=labels>0
        assert not np.any(loss&~valid)
        assert not np.any(scrape&oldfoil)
        assert np.array_equal(valid,grid&~scrape&~oldfoil)
        base=np.stack([display(t)]*3,axis=2)
        m=reg['matrix'];cells=[]
        lines=Image.new('L',(1440,1080));draw=ImageDraw.Draw(lines)
        for refcell in geom['images'][i-1]['cells']:
            poly=transform_xy(np.array(refcell['polygon_xy']),m)
            center=transform_xy(np.array([refcell['centroid_xy']]),m)[0]
            cell={'cell_id':refcell['cell_id'],'row_from_top_0_based':refcell['row_from_top_0_based'],'column_from_left_0_based':refcell['column_from_left_0_based'],'centroid_xy':center.tolist(),'polygon_xy':poly.round(3).tolist()}
            cells.append(cell)
            draw.line([tuple(p) for p in np.vstack([poly,poly[0]])],fill=255,width=3)
        boundary=np.array(lines)>0
        labelcounts=np.bincount(labels.ravel(),minlength=82)
        eligible=np.bincount(labels[valid].ravel(),minlength=82)
        losscounts=np.bincount(labels[loss].ravel(),minlength=82)
        scrapecounts=np.bincount(labels[scrape].ravel(),minlength=82)
        oldcounts=np.bincount(labels[oldfoil].ravel(),minlength=82)
        status=np.zeros(82,dtype=np.uint8)
        rowcells=[]
        for cid in range(81):
            k=cid+1;used=int(eligible[k]);lost=int(losscounts[k]);retained=used-lost
            if used==0: name='Excluded';status[k]=3
            elif lost>0:name='Damaged';status[k]=2
            else:name='Intact';status[k]=1
            row={'image':f'S13_Taped_[{i}]','cell_id':cid,'row_from_top_1_based':cid//9+1,'column_from_left_1_based':cid%9+1,'grid_pixels':int(labelcounts[k]),'scrape_excluded_pixels':int(scrapecounts[k]),'preexisting_foil_excluded_pixels':int(oldcounts[k]),'eligible_AM_pixels':used,'loss_pixels':lost,'retained_pixels':retained,'loss_pct':100*lost/used if used else None,'retained_pct':100*retained/used if used else None,'status':name}
            assert row['grid_pixels']==row['scrape_excluded_pixels']+row['preexisting_foil_excluded_pixels']+used
            rowcells.append(row);allcells.append(row)
        intact=int((status[1:]==1).sum());damaged=int((status[1:]==2).sum());excluded=int((status[1:]==3).sum())
        summary={'image':f'S13_Taped_[{i}]','columns_horizontal':9,'rows_vertical':9,'total_cells':81,'intact_no_detected_loss_cells':intact,'damaged_cells':damaged,'excluded_cells':excluded,'eligible_AM_pixels':int(valid.sum()),'loss_pixels':int(loss.sum()),'retained_pixels':int(valid.sum()-loss.sum()),'retained_AM_pct':100*(valid.sum()-loss.sum())/valid.sum(),'peeled_AM_pct':100*loss.sum()/valid.sum(),'scrape_excluded_pixels':int(scrape.sum()),'preexisting_foil_excluded_pixels':int(oldfoil.sum())}
        assert intact+damaged+excluded==81
        summaries.append(summary)
        for item in seg_stats[i-1]['thresholds']:
            sweeps.append({'image':summary['image'],**item})

        green=base.copy();green[boundary]=GREEN;save(green,f'S13_Taped_{i}_Green_Boundaries.png')
        yellow=base.copy();tint(yellow,grid,YELLOW,.23);yellow[boundary]=GREEN
        save(yellow,f'S13_Taped_{i}_Yellow_Cells.png')
        save(numbered(yellow,cells),f'S13_Taped_{i}_Numbered_0-80.png')
        classification=base.copy()
        for code,color in [(1,YELLOW),(2,ORANGE),(3,RED)]:tint(classification,status[labels]==code,color,.23)
        classification[boundary]=GREEN
        save(classification,f'S13_Taped_{i}_Cell_Status.png')
        blue=base.copy();tint(blue,loss,BLUE,.70);save(blue,f'S13_Taped_{i}_AM_Loss_Blue.png')
        combined=classification.copy();tint(combined,loss,BLUE,.75);combined[boundary]=GREEN
        save(numbered(combined,cells),f'S13_Taped_{i}_All_Annotations.png')
        # Explicitly show the pixels excluded from both numerator and denominator.
        ex=base.copy();tint(ex,scrape|oldfoil,RED,.55);ex[boundary]=GREEN
        save(ex,f'S13_Taped_{i}_Excluded_Areas.png')
        rw=np.nan_to_num(data['reference_aligned'],nan=0.)*np.exp(data['normalization_log'])
        refdisplay=display(rw)
        aligned=Image.fromarray(refdisplay);aligned.save(OUT/f'S13_Squared_{i}_Aligned_To_Taped.png')
        overlay=np.stack([refdisplay,display(t),display(t)],axis=2)
        save(overlay,f'S13_Pair_{i}_Aligned_Red_Cyan_Overlay.png')
        # The masks are exact native-Taped pixel masks; blue is never dilated.
        Image.fromarray(labels.astype(np.uint16)).save(DATA/f'S13_Taped_{i}_Cell_ID_Mask.tif')
        for name,mask in [('AM_Loss_Mask',loss),('Eligible_AM_Mask',valid),('Original_Scrape_Exclusion_Mask',scrape),('Preexisting_Foil_Exclusion_Mask',oldfoil),('Green_Boundary_Mask',boundary)]:
            Image.fromarray(mask.astype(np.uint8)*255).save(DATA/f'S13_Taped_{i}_{name}.png')
        rgba=np.zeros((1080,1440,4),dtype=np.uint8);rgba[loss,:3]=BLUE;rgba[loss,3]=178
        Image.fromarray(rgba).save(DATA/f'S13_Taped_{i}_Transparent_Blue_Loss_Overlay.png')
        write_csv(OUT/f'S13_Taped_{i}_Per_Cell_Results.csv',rowcells)
        tapedgeometry.append({'taped_source':f'S13_Taped_[{i}].tif','squared_source':f'S13_Squared_[{i}].tif','matrix_Squared_to_Taped':m.tolist(),'independently_observed_grid':{'rows':9,'columns':9,'cells':81},'cells':cells})
        for kind in ['Squared','Taped']:
            path=ROOT/'upload'/f'S13_{kind}_[{i}].tif'
            sourcehashes.append({'filename':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'dtype':'uint16','dimensions':[1440,1080]})

    write_csv(OUT/'S13_Step2_Summary.csv',summaries)
    write_csv(OUT/'S13_Step2_All_Per_Cell_Results.csv',allcells)
    write_csv(OUT/'S13_Step2_Threshold_Comparison.csv',sweeps)
    means=[]
    for cid in range(81):
        records=[row for row in allcells if row['cell_id']==cid]
        vals=[r['loss_pct'] for r in records]
        means.append({'cell_id':cid,'row_from_top_1_based':cid//9+1,'column_from_left_1_based':cid%9+1,'mean_loss_pct':float(np.mean(vals)),'mean_retained_pct':float(100-np.mean(vals)),'min_loss_pct':float(np.min(vals)),'max_loss_pct':float(np.max(vals)),'views_with_detected_loss':sum(r['loss_pixels']>0 for r in records)})
    write_csv(OUT/'S13_Step2_Per_Cell_Means.csv',means)
    (DATA/'S13_Taped_Grid_Geometry.json').write_text(json.dumps({'coordinate_system':'Original Taped pixels, origin upper-left, x right, y down. Original source orientation retained.','numbering':'0..80, left-to-right then top-to-bottom. Cell labels 1..81 map to displayed IDs 0..80. Label 0 means outside.','geometry_note':'Taped counts checked independently. The registered Step-1 curved paths provide the corresponding cell identities and exclude the original cuts. Faint segments are interpolated.','images':tapedgeometry},indent=2))
    (DATA/'S13_Analysis_Parameters.json').write_text(json.dumps({'sources':sourcehashes,'registration':reg_stats,'segmentation':seg_stats,'primary_setting':'High','formula':'loss_pct = 100 * measured_loss_mask_pixels / eligible_original_AM_mask_pixels; retained_pct = 100 - loss_pct','mean_of_repeated_views':float(np.mean([r['peeled_AM_pct'] for r in summaries])),'independent_specimens':1,'repeated_views':4,'minimum_connected_component_pixels':3,'connectivity':8,'cut_registration_safety_buffer_pixels':2,'limitations':['Grayscale optical candidates are consistent with AM loss but do not chemically establish exposed aluminium.','Illumination, coating roughness and subpixel alignment affect very small bright features.','No loss detected does not establish physical zero damage.','The threshold comparison is an operational sensitivity sweep, not a statistical confidence interval.']},indent=2))
    (WORK/'S13_Workbook_Data.json').write_text(json.dumps({'summary':summaries,'cells':allcells,'means':means,'thresholds':sweeps},indent=2))

    header='S13 STEP-2: GRID COUNTS\n\nCounted from the visible Taped grid. Columns are horizontal, rows vertical.\n\n'
    table='Image               Columns  Rows  Total  Numbering\n'+'-'*54+'\n'
    for row in summaries:table+=f"{row['image']:<21}9        9     81     0-80\n"
    (OUT/'S13_Step2_Grid_Counts.txt').write_text(header+table+'\nThe four images are repeated views of the same 81 physical cells.\nNumbering starts in the upper-left enclosed cell and proceeds left to right,\nthen down to the next row. Cell ID = 9 * zero-based row + zero-based column.\nThe unbounded coating outside the ten vertical and ten horizontal grid cuts\nis outside the measured grid. Faint cut segments are interpolated.\n')

    lines=['S13 STEP-2 ADHESION AREA ESTIMATE','', 'Primary result: HIGH SENSITIVITY optical classification.','', 'Image             Intact  Damaged  Excluded  Retained AM (%)  Peeled AM (%)']
    for row in summaries:
        lines.append(f"{row['image']:<18}{row['intact_no_detected_loss_cells']:>6}{row['damaged_cells']:>9}{row['excluded_cells']:>10}{row['retained_AM_pct']:>17.4f}{row['peeled_AM_pct']:>15.4f}")
    meanloss=float(np.mean([r['peeled_AM_pct'] for r in summaries]))
    lines.extend(['',f'Mean across the four views: retained AM {100-meanloss:.4f}%; peeled AM {meanloss:.4f}%.','', 'AREA DEFINITION','Retained AM means eligible original coated area with no detected new loss.','Eligible original AM excludes the original tool-scraped cut bands, a small','registration safety margin, pre-existing bright foil candidates and the','area outside the enclosed grid. These exclusions apply to numerator and','denominator. No whole cells were excluded.','Loss (%) = 100 * new loss pixels / eligible original AM pixels.','Retained (%) = 100 - loss (%).','A damaged cell has at least one retained connected loss component.','An intact cell has no loss detected by this setting. This does not prove','physical zero damage. Severity is expressed as area loss, without assigning','an ASTM or other standardized test grade.','', 'REGISTRATION AND RAW SIGNAL','Each Squared image was paired only with its matching Taped image. An affine','transform fitted to stable texture/cut matches corrects translation, small','rotation and scale. The native Taped orientation and dimensions are kept.','Measurements use original 16-bit containers containing approximately','10-bit signal. A 0.6-pixel Gaussian smoothing suppresses sensor noise.','A robust second-order spatial fit to paired log-intensity ratios corrects','exposure/illumination differences. It is fitted from cell interiors away','from cuts. The fixed sqrt(raw/1023) display mapping is not used to measure','loss. The aligned reference display has exposure correction applied.','', 'ORIGINAL SCRAPE EXCLUSION','The Step-1 curved cut centerlines are retained. Connected dark or bright','original groove pixels near the cut centerlines extend the exclusion','locally. A two-pixel margin covers alignment uncertainty. Bright original','interior foil candidates are excluded separately. The exact excluded-pixel','masks are provided. New bright material-loss regions extending beyond the','original excluded bands can be included. The safety margin can omit a','small amount of loss immediately beside a pre-existing cut.','', 'HIGH-SENSITIVITY DETECTION','A counted loss pixel must satisfy ALL of the following:','1. It lies in the eligible original-AM region.','2. Its local Taped intensity is at least 1.5 times the fitted local coating','   background.','3. Its paired log-intensity increase exceeds max(0.22, 2.0 * sigma), after','   exposure correction. Sigma is estimated robustly from negative residuals','   in stable cell interiors.','4. It belongs to an eight-connected component of at least three pixels.','Blue pixels exactly match the measured loss masks. They are not expanded','or dilated for display.','', 'THRESHOLD COMPARISON','These operational settings show threshold dependence. They are not a','statistical confidence interval or proof of material identity.','High: local brightness ratio 1.5; paired change 2.0 sigma (primary).','Moderate: ratio 1.7; paired change 2.5 sigma.','Conservative: ratio 2.0; paired change 3.0 sigma.','', 'Image             High loss (%)  Moderate loss (%)  Conservative loss (%)'])
    for i in range(4):
        t=seg_stats[i]['thresholds'];lines.append(f"S13_Taped_[{i+1}]    {t[0]['loss_pct']:>11.4f}{t[1]['loss_pct']:>19.4f}{t[2]['loss_pct']:>23.4f}")
    lines.extend(['', 'INTERPRETATION','The blue regions are high-sensitivity optical candidates for new exposed','substrate or reduced coating coverage. Fine bright texture can also change','with illumination or surface roughness. Large bright changes next to cuts','are clearer than tiny isolated clusters. The estimate describes visible','area retention in this image field, not adhesion force, retained mass,','coating thickness or a standardized classification.','The four views repeat one specimen. They are not four independent samples.','Their arithmetic mean summarizes repeated-view estimates. No precision','beyond the image analysis and chosen thresholds is implied.','', 'COLOURS','Green: grid boundaries.','Light yellow: cell has no detected new AM loss.','Orange: cell contains detected candidate loss.','Red: excluded whole cell (none in this set).','Light blue: exact candidate loss pixels used in the calculation.','On the separate Excluded_Areas images, red marks excluded PIXELS only.','', 'ALIGNMENT CHECK','Aligned_Red_Cyan_Overlay images place the normalized Squared image in the','red channel and Taped image in the cyan channels. Aligned common features','appear gray/white. Colour differences show changes or residual mismatch;','they do not themselves constitute the measured loss mask.'])
    (OUT/'S13_Step2_Method_and_Results.txt').write_text('\n'.join(lines)+'\n')
    (OUT/'S13_Step2_File_Guide.txt').write_text('S13 STEP-2 FILE GUIDE\n\nAll_Annotations.png: green cuts, yellow/orange/red cell status, cell IDs\n0-80, and exact light-blue loss pixels in one native-size image.\nGreen_Boundaries.png: boundary-only view.\nYellow_Cells.png: transparent light-yellow cells with green boundaries.\nNumbered_0-80.png: green/yellow grid with separate cell numbers.\nCell_Status.png: yellow intact, orange damaged, red excluded cells.\nAM_Loss_Blue.png: exact measured candidate loss areas, without numbers.\nExcluded_Areas.png: red excluded original-scrape/foil pixels; green cuts.\nSquared_Aligned_To_Taped.png: registered, exposure-corrected reference.\nAligned_Red_Cyan_Overlay.png: overlapping Squared and Taped comparison.\n\nSummary.csv and Results.xlsx: per-image counts and area percentages.\nAll_Per_Cell_Results.csv and the four per-image CSVs: full cell detail.\nPer_Cell_Means.csv: per-cell average across the repeated views.\nThreshold_Comparison.csv: high/moderate/conservative operational results.\nGrid_Counts.txt: the independently checked grid count table.\nMethod_and_Results.txt: area definitions, processing, settings, limitations.\n\nReusable_Data contains exact masks, transformed curved cell polygons,\ncentroids, affine transformations, settings and source SHA-256 hashes.\nCell_ID_Mask.tif uses values 1-81 for displayed IDs 0-80. Value 0 is outside.\nBinary masks use 255 for included/marked pixels and 0 elsewhere.\nTransparent_Blue_Loss_Overlay.png is an RGBA overlay with no background.\n\nAll annotated per-image PNGs are lossless 1440 x 1080 pixels.\nThe original uploaded TIFF files have not been modified.\n')

    # Compact previews show all four annotated source-coordinate images.
    for suffix,target in [('All_Annotations','S13_Step2_Annotated_Preview.png'),('Numbered_0-80','S13_Step2_Numbered_Preview.png')]:
        canvas=Image.new('RGB',(1920,1600),'white');draw=ImageDraw.Draw(canvas)
        draw.text((25,18),'S13 adhesion analysis: high sensitivity',font=LARGE,fill=(20,35,48))
        for i in range(1,5):
            x=((i-1)%2)*960;y=((i-1)//2)*760+65
            im=Image.open(OUT/f'S13_Taped_{i}_{suffix}.png').resize((960,720),Image.Resampling.LANCZOS)
            canvas.paste(im,(x,y+28));draw.text((x+12,y),f"Taped {i}     81 cells     Retained {summaries[i-1]['retained_AM_pct']:.2f}%     Loss {summaries[i-1]['peeled_AM_pct']:.2f}%",font=SMALL,fill=(20,35,48))
        draw.text((25,1580),'Green: cuts    Yellow: no loss detected    Orange: loss detected    Blue: exact loss pixels    No excluded cells',font=SMALL,fill=(20,35,48))
        canvas.save(OUT/target)
    print(json.dumps({'summary':summaries,'mean_loss_pct':meanloss,'mean_retained_pct':100-meanloss,'output_files':len(list(OUT.rglob('*')))},indent=2))

if __name__=='__main__':main()
