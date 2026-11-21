"""Re-threshold the audited S13 paired signals at 5.0x sensitivity."""
from pathlib import Path
import csv, hashlib, json, os
import numpy as np
from scipy import ndimage as ndi
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(os.environ.get('S13_PROJECT_ROOT','/workspace/scratch/e5a7a5c0c1d8'))
WORK=ROOT/'work';BASE=ROOT/'S13_Step2';OUT=ROOT/'S13_Step2_5x'
REUSE=OUT/'Reusable_Data';REUSE.mkdir(parents=True,exist_ok=True)
FACTOR=5.0
GREEN=np.array([0,230,60]);YELLOW=np.array([255,245,150]);ORANGE=np.array([255,165,65]);RED=np.array([255,90,90]);BLUE=np.array([100,205,255])
FONT=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',17)
SMALL=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',16)
LARGE=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',25)

def components(mask):
    lab,n=ndi.label(mask,np.ones((3,3),bool))
    areas=np.bincount(lab.ravel());keep=areas>=3;keep[0]=False
    return keep[lab]

def display(a):return np.uint8(np.clip(np.sqrt(np.maximum(a,0)/1023)*255,0,255))

def tint(a,mask,color,alpha):a[mask]=np.uint8(np.rint(a[mask]*(1-alpha)+color*alpha))

def numbered(a,cells):
    img=Image.fromarray(a);d=ImageDraw.Draw(img,'RGBA')
    for cell in cells:
        x,y=cell['centroid_xy'];text=str(cell['cell_id'])
        box=d.textbbox((x,y),text,font=FONT,anchor='mm')
        d.rounded_rectangle((box[0]-3,box[1]-2,box[2]+3,box[3]+2),radius=3,fill=(255,255,225,140))
        d.text((x,y),text,font=FONT,anchor='mm',fill=(0,0,0,255))
    return img

def write_csv(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def binary(path,a):Image.fromarray(a.astype(np.uint8)*255).save(path)

def main():
    geometry=json.loads((BASE/'Reusable_Data/S13_Taped_Grid_Geometry.json').read_text())
    baseline=json.loads((WORK/'S13_Workbook_Data.json').read_text())
    params=json.loads((BASE/'Reusable_Data/S13_Analysis_Parameters.json').read_text())
    summaries=[];rows=[];thresholds=[];mask_checks=[]
    for i in range(1,5):
        dat=np.load(WORK/f'S13_Segmentation_{i}.npz')
        labels=dat['labels'];valid=dat['valid'];old=dat['loss'];scrape=dat['scrape'];oldfoil=dat['oldfoil']
        # Confirm that cached paired signals have the same masks as the delivered 1x analysis.
        for name,expected in [('AM_Loss_Mask',old),('Eligible_AM_Mask',valid),('Original_Scrape_Exclusion_Mask',scrape),('Preexisting_Foil_Exclusion_Mask',oldfoil)]:
            stored=np.array(Image.open(BASE/'Reusable_Data'/f'S13_Taped_{i}_{name}.png'))>0
            assert np.array_equal(stored,expected),(i,name)
        assert np.array_equal(labels,np.array(Image.open(BASE/'Reusable_Data'/f'S13_Taped_{i}_Cell_ID_Mask.tif')))
        old_dt=float(dat['delta_threshold']);old_bt=float(dat['brightness_threshold'])
        new_dt=old_dt/FACTOR;new_bt=old_bt/FACTOR
        loss=components(valid&(dat['delta']>new_dt)&(dat['brightness']>new_bt))
        added=loss&~old
        assert not np.any(old&~loss)
        assert not np.any(loss&~valid)
        assert not np.any(loss&(scrape|oldfoil))
        assert np.array_equal(valid,(labels>0)&~scrape&~oldfoil)
        den=np.bincount(labels[valid],minlength=82)
        l1=np.bincount(labels[old],minlength=82)
        l5=np.bincount(labels[loss],minlength=82)
        grids=np.bincount(labels.ravel(),minlength=82)
        scr=np.bincount(labels[scrape],minlength=82)
        pre=np.bincount(labels[oldfoil],minlength=82)
        status=np.zeros(82,np.uint8);image_rows=[]
        for cid in range(81):
            k=cid+1;used=int(den[k]);n1=int(l1[k]);n5=int(l5[k])
            name='Excluded' if used==0 else ('Damaged' if n5>0 else 'Intact')
            status[k]={'Excluded':3,'Damaged':2,'Intact':1}[name]
            r={'image':f'S13_Taped_[{i}]','cell_id':cid,'row_from_top_1_based':cid//9+1,'column_from_left_1_based':cid%9+1,'grid_pixels':int(grids[k]),'scrape_excluded_pixels':int(scr[k]),'preexisting_foil_excluded_pixels':int(pre[k]),'eligible_AM_pixels':used,'baseline_loss_pixels':n1,'loss_pixels':n5,'additional_loss_pixels':n5-n1,'retained_pixels':used-n5,'baseline_loss_pct':100*n1/used if used else None,'loss_pct':100*n5/used if used else None,'retained_pct':100*(used-n5)/used if used else None,'increase_percentage_points':100*(n5-n1)/used if used else None,'status':name}
            assert r['grid_pixels']==used+r['scrape_excluded_pixels']+r['preexisting_foil_excluded_pixels']
            rows.append(r);image_rows.append(r)
        used=int(valid.sum());lost=int(loss.sum());prev=int(old.sum())
        summary={'image':f'S13_Taped_[{i}]','sensitivity_factor':FACTOR,'columns_horizontal':9,'rows_vertical':9,'total_cells':81,'intact_no_detected_loss_cells':int((status[1:]==1).sum()),'damaged_cells':int((status[1:]==2).sum()),'excluded_cells':int((status[1:]==3).sum()),'eligible_AM_pixels':used,'baseline_loss_pixels':prev,'loss_pixels':lost,'additional_loss_pixels':int(added.sum()),'retained_pixels':used-lost,'baseline_loss_pct':100*prev/used,'peeled_AM_pct':100*lost/used,'retained_AM_pct':100*(used-lost)/used,'increase_percentage_points':100*(lost-prev)/used,'scrape_excluded_pixels':int(scrape.sum()),'preexisting_foil_excluded_pixels':int(oldfoil.sum())}
        old_summary=baseline['summary'][i-1]
        assert used==old_summary['eligible_AM_pixels'] and prev==old_summary['loss_pixels']
        assert summary['intact_no_detected_loss_cells']+summary['damaged_cells']+summary['excluded_cells']==81
        summaries.append(summary)
        sigma=params['segmentation'][i-1]['noise_log_ratio']
        thresholds.append({'image':summary['image'],'sensitivity_factor':FACTOR,'baseline_paired_log_threshold':old_dt,'updated_paired_log_threshold':new_dt,'baseline_brightness_log_threshold':old_bt,'updated_brightness_log_threshold':new_bt,'baseline_local_brightness_ratio':float(np.exp(old_bt)),'updated_local_brightness_ratio':float(np.exp(new_bt)),'measured_log_residual_sigma':sigma,'updated_paired_threshold_in_sigma':new_dt/sigma,'minimum_connected_component_pixels':3,'connectivity':8})

        t=np.array(Image.open(ROOT/'upload'/f'S13_Taped_[{i}].tif'),dtype=np.float32)
        gray=display(t);base=np.stack([gray]*3,axis=2)
        boundary=np.array(Image.open(BASE/'Reusable_Data'/f'S13_Taped_{i}_Green_Boundary_Mask.png'))>0
        assert not np.any(boundary&loss)
        cells=geometry['images'][i-1]['cells']
        classification=base.copy()
        for code,col in [(1,YELLOW),(2,ORANGE),(3,RED)]:tint(classification,status[labels]==code,col,.23)
        classification[boundary]=GREEN
        Image.fromarray(classification).save(OUT/f'S13_Taped_{i}_Cell_Status_5x.png')
        blue=base.copy();tint(blue,loss,BLUE,.70)
        Image.fromarray(blue).save(OUT/f'S13_Taped_{i}_AM_Loss_Blue_5x.png')
        newblue=base.copy();tint(newblue,added,BLUE,.70)
        Image.fromarray(newblue).save(OUT/f'S13_Taped_{i}_Additional_Loss_5x.png')
        combined=classification.copy();tint(combined,loss,BLUE,.75);combined[boundary]=GREEN
        numbered(combined,cells).save(OUT/f'S13_Taped_{i}_All_Annotations_5x.png')
        comp=Image.new('RGB',(1920,785),'white');d=ImageDraw.Draw(comp)
        for col,mask,label,pct in [(0,old,'Previous 1.0x',summary['baseline_loss_pct']),(1,loss,'Updated 5.0x',summary['peeled_AM_pct'])]:
            img=base.copy();tint(img,mask,BLUE,.70);img[boundary]=GREEN
            comp.paste(Image.fromarray(img).resize((960,720),Image.Resampling.LANCZOS),(col*960,60))
            d.text((col*960+15,15),f'Taped {i}   {label}   Candidate loss {pct:.2f}%',font=LARGE,fill=(20,35,48))
        comp.save(OUT/f'S13_Taped_{i}_Comparison_1x_vs_5x.png')
        for tag,mask in [('AM_Loss_Mask_5x',loss),('Additional_Loss_Mask_5x',added),('Baseline_AM_Loss_Mask_1x',old),('Eligible_AM_Mask_5x',valid),('Original_Scrape_Exclusion_Mask_5x',scrape),('Preexisting_Foil_Exclusion_Mask_5x',oldfoil),('Green_Boundary_Mask_5x',boundary)]:
            binary(REUSE/f'S13_Taped_{i}_{tag}.png',mask)
        Image.fromarray(labels.astype(np.uint16)).save(REUSE/f'S13_Taped_{i}_Cell_ID_Mask_5x.tif')
        rgba=np.zeros((1080,1440,4),np.uint8);rgba[loss,:3]=BLUE;rgba[loss,3]=178
        Image.fromarray(rgba).save(REUSE/f'S13_Taped_{i}_Transparent_Blue_Loss_Overlay_5x.png')
        write_csv(OUT/f'S13_Taped_{i}_Per_Cell_Results_5x.csv',image_rows)
        mask_checks.append({'image':summary['image'],'baseline_mask_subset_of_updated':True,'eligible_and_exclusion_masks_unchanged':True,'loss_pixels':lost,'eligible_pixels':used,'no_measured_loss_on_excluded_pixels':True,'loss_mask_sha256':hashlib.sha256(loss.tobytes()).hexdigest()})

    mean1=float(np.mean([s['baseline_loss_pct'] for s in summaries]));mean5=float(np.mean([s['peeled_AM_pct'] for s in summaries]))
    means=[]
    for cid in range(81):
        obs=[r for r in rows if r['cell_id']==cid]
        means.append({'cell_id':cid,'row_from_top_1_based':cid//9+1,'column_from_left_1_based':cid%9+1,'mean_baseline_loss_pct':float(np.mean([r['baseline_loss_pct'] for r in obs])),'mean_loss_pct_5x':float(np.mean([r['loss_pct'] for r in obs])),'mean_retained_pct_5x':float(np.mean([r['retained_pct'] for r in obs])),'min_loss_pct_5x':min(r['loss_pct'] for r in obs),'max_loss_pct_5x':max(r['loss_pct'] for r in obs),'views_with_detected_loss':sum(r['loss_pixels']>0 for r in obs)})
    write_csv(OUT/'S13_Step2_Summary_5x.csv',summaries)
    write_csv(OUT/'S13_Step2_All_Per_Cell_Results_5x.csv',rows)
    write_csv(OUT/'S13_Step2_Per_Cell_Means_5x.csv',means)
    write_csv(OUT/'S13_Step2_Thresholds_5x.csv',thresholds)
    write_csv(OUT/'S13_Step2_Comparison_1x_vs_5x.csv',[{'image':s['image'],'loss_pct_1x':s['baseline_loss_pct'],'loss_pct_5x':s['peeled_AM_pct'],'retained_pct_5x':s['retained_AM_pct'],'increase_percentage_points':s['increase_percentage_points']} for s in summaries])
    (REUSE/'S13_Taped_Grid_Geometry_5x.json').write_text(json.dumps(geometry,indent=2))
    newparams={'sensitivity_factor':FACTOR,'definition':'Divide BOTH original positive log-contrast thresholds by 5.0; do not multiply the measured loss percentage.','threshold_formula':{'paired_log_threshold':'original_paired_log_threshold / 5.0','brightness_log_threshold':'log(1.5) / 5.0','brightness_ratio':'1.5 ** (1/5) = 1.0844717712'},'primary_setting':'5.0x candidate-loss sensitivity scenario','thresholds':thresholds,'registration_and_normalization':'Reuse the exact audited paired transforms, corrected signals and original eligible/exclusion masks.','minimum_connected_component_pixels':3,'connectivity':8,'mean_baseline_loss_pct':mean1,'mean_updated_loss_pct':mean5,'mean_updated_retained_pct':100-mean5,'baseline_analysis_parameters':params,'validation':mask_checks,'interpretation':'The paired detection threshold is 0.4 times measured residual sigma. Brightness thresholds fall within normal image variation. Faint coating texture, lighting and registration variation contribute to these candidates; the 5.0x result is not a validated physical AM-loss measurement.'}
    (REUSE/'S13_Analysis_Parameters_5x.json').write_text(json.dumps(newparams,indent=2))
    (WORK/'S13_Workbook_Data_5x.json').write_text(json.dumps({'summary':summaries,'cells':rows,'means':means,'thresholds':thresholds,'mean_baseline_loss_pct':mean1,'mean_loss_pct':mean5},indent=2))

    counts=['S13 STEP-2 GRID COUNTS AT 5.0x SENSITIVITY','','Image               Columns  Rows  Total  Numbering']
    for i in range(1,5):counts.append(f'S13_Taped_[{i}]       9        9     81     0-80')
    counts+=['','The same measured grid is used for the 1.0x and 5.0x runs.','All 81 cells are included in each image. Original scraped cut pixels and','pre-existing foil candidates remain excluded from the measured AM area.','The four views describe one physical 81-cell specimen.']
    (OUT/'S13_Step2_Grid_Counts_5x.txt').write_text('\n'.join(counts)+'\n')
    text=['S13 STEP-2 UPDATED RESULTS: 5.0x SENSITIVITY','','OPERATIONAL DEFINITION','Sensitivity factor 5.0 is implemented by dividing BOTH original log-contrast','thresholds by 5.0. This is a detector-setting change. The area percentages','are recalculated by classifying the paired pixels at the new thresholds.','The detected area is not expected to increase by exactly five times.','','Original brightness ratio 1.5 becomes 1.5^(1/5) = 1.0844717712.','Original paired thresholds max(0.22, 2*sigma) become that full value / 5.0.','For these four images, the updated paired threshold equals 0.4*sigma.','The original 3-pixel, 8-connected component requirement remains in place.','','IMPORTANT INTERPRETATION','The updated thresholds are below the measured brightness variation. They','admit faint coating texture, lighting differences and residual alignment','effects. Blue marks candidate material-loss pixels at this sensitivity.','A percentage calculated from these pixels is an optical sensitivity','estimate. The images do not confirm that every new blue pixel is bare Al.','The physical sample has not changed between the two calculations.','','RESULTS','Image            No loss  Damaged Excluded  Retained (%) Candidate loss (%)']
    for s in summaries:text.append(f"{s['image']:<18}{s['intact_no_detected_loss_cells']:>5}{s['damaged_cells']:>9}{s['excluded_cells']:>9}{s['retained_AM_pct']:>14.4f}{s['peeled_AM_pct']:>19.4f}")
    text += ['',f'Mean 5.0x candidate loss: {mean5:.4f}%.',f'Mean 5.0x remaining-area estimate: {100-mean5:.4f}%.',f'Previous mean candidate loss: {mean1:.4f}%.',f'Increase: {mean5-mean1:.4f} percentage points.','','AREA CALCULATION','Candidate loss (%) = 100 * selected blue pixels / eligible original AM pixels.','Remaining-area estimate (%) = 100 - candidate loss (%).','Registration, illumination correction, curved cell geometry, cell IDs,','original scrape exclusions and original bare-foil exclusions are identical','to the previous calculation. No whole cells are excluded.','All original loss pixels remain included in the updated masks.','Blue masks are not dilated for display.','','CELL CLASSIFICATION','Yellow: no detected loss. Orange: at least one detected candidate component.','Red: whole cell excluded (none). Green: registered grid boundary.','At this 5.0x setting, every cell contains at least one candidate component.','This does not mean every cell has substantial physical material removal.','','REPEATED VIEWS','The mean is the arithmetic average of the four image-level area estimates.','The images are repeated views of one specimen, not independent specimens.','','THRESHOLDS','Image            Paired log 1x  Paired log 5x  Bright log 1x  Bright log 5x']
    for r in thresholds:text.append(f"{r['image']:<18}{r['baseline_paired_log_threshold']:>12.6f}{r['updated_paired_log_threshold']:>15.6f}{r['baseline_brightness_log_threshold']:>15.6f}{r['updated_brightness_log_threshold']:>15.6f}")
    (OUT/'S13_Step2_Method_and_Results_5x.txt').write_text('\n'.join(text)+'\n')
    (OUT/'S13_Step2_File_Guide_5x.txt').write_text('S13 UPDATED ANALYSIS AT 5.0x SENSITIVITY\n\nAll_Annotations_5x: green boundaries, cell IDs 0-80, yellow/orange/red cell\nstatus and light-blue candidate loss pixels in one original-size image.\nAM_Loss_Blue_5x: exact candidate loss pixels.\nAdditional_Loss_5x: only pixels newly admitted relative to the 1.0x mask.\nCell_Status_5x: whole-cell classification at the updated setting.\nComparison_1x_vs_5x: paired views of previous and updated loss overlays.\nResults_5x.xlsx: summary and 324 per-cell observations with formulas.\nCSV tables: summary, per-cell results, per-cell means, thresholds and comparison.\nGrid_Counts_5x.txt: the 9 by 9 grid count for each image.\nMethod_and_Results_5x.txt: full threshold definition, results and limitations.\nReusable_Data: exact loss, added-loss, original baseline, eligible-area and\nexclusion masks, original cell labels, geometry and analysis settings.\n\nBinary masks use 255 for selected pixels and 0 elsewhere.\nCell label masks use 1-81 for displayed IDs 0-80. Label 0 means outside.\nPer-image annotations retain the original 1440 by 1080 dimensions/orientation.\nBlue pixels are not expanded for display. The original source TIFFs and\nthe previous 1.0x deliverables have not been modified.\n')
    preview=Image.new('RGB',(1920,1640),'white');d=ImageDraw.Draw(preview)
    d.text((25,15),'S13: 5.0x sensitivity, candidate material loss',font=LARGE,fill=(20,35,48))
    d.text((25,50),'Both original contrast thresholds divided by 5. Fine texture and lighting changes are also admitted.',font=SMALL,fill=(20,35,48))
    for i in range(1,5):
        x=(i-1)%2*960;y=(i-1)//2*760+85
        d.text((x+12,y),f"Taped {i}    Remaining {summaries[i-1]['retained_AM_pct']:.2f}%    Candidate loss {summaries[i-1]['peeled_AM_pct']:.2f}%",font=SMALL,fill=(20,35,48))
        im=Image.open(OUT/f'S13_Taped_{i}_All_Annotations_5x.png').resize((960,720),Image.Resampling.LANCZOS)
        preview.paste(im,(x,y+28))
    d.text((25,1620),'Green: cuts    Orange: candidate loss detected in cell    Blue: exact selected pixels    No excluded cells',font=SMALL,fill=(20,35,48))
    preview.save(OUT/'S13_Step2_Annotated_Preview_5x.png')
    print(json.dumps({'summary':summaries,'mean_1x_loss_pct':mean1,'mean_5x_loss_pct':mean5,'mean_5x_retained_pct':100-mean5},indent=2))

if __name__=='__main__':main()
