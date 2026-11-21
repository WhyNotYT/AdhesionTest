from pathlib import Path
import json
import numpy as np
from PIL import Image,ImageDraw
from scipy.ndimage import gaussian_filter,map_coordinates,distance_transform_edt,binary_propagation,binary_dilation,binary_fill_holes,label

import os
ROOT=Path(os.environ.get('S16_WORK_DIR', Path.cwd()));ANA=ROOT/'analysis'
GRID=ROOT/'recovered'/'S16_Step1'/'Reusable_Grid_Data'
definitions=json.loads((GRID/'S16_Step1_Grid_Definitions.json').read_text())

def components(mask,seeds,min_size=5):
    cc,n=label(mask,structure=np.ones((3,3)))
    size=np.bincount(cc.ravel());se=np.unique(cc[seeds]);keep=np.zeros(n+1,bool)
    keep[se]=True;keep[0]=False;keep&=(size>=min_size)
    result=keep[cc]
    # Fill only small enclosed islands, never broad cell interiors.
    holes=binary_fill_holes(result)&~result
    hc,hn=label(holes,structure=np.ones((3,3)));hs=np.bincount(hc.ravel())
    small=hs<=30;small[0]=False
    return result|small[hc]

metrics=[]
for i in range(1,5):
    ref=np.asarray(Image.open(ROOT/'references'/f'S16_Squared_[{i}].tif')).astype(float)
    tape=np.asarray(Image.open(ROOT/'upload'/f'S16_Taped_[{i}].tif')).astype(float)
    reg=np.load(ANA/f'registration_{i}.npz');my=reg['map_y'];mx=reg['map_x']
    gd=definitions['images'][i-1]
    orig_labels=np.asarray(Image.open(GRID/f'S16_Squared_{i}_Cell_IDs_1-81.png'))
    cell_labels=map_coordinates(orig_labels,[my,mx],order=0,mode='constant',cval=0).astype(np.uint16)
    lines=Image.new('L',(1440,1080),0);ld=ImageDraw.Draw(lines)
    for line in gd['horizontal_boundary_paths_px']+gd['vertical_boundary_paths_px']:
        ld.line([tuple(p) for p in line],fill=255,width=1)
    centre=np.asarray(lines)>0
    dist=distance_transform_edt(~centre)
    bg=gaussian_filter(ref,7)
    signed=(bg-gaussian_filter(ref,.8))/(bg+5)
    cut_contrast=(signed>.40)|(signed<-.65)
    strong_cut=(signed>.55)|(signed<-.95)
    core=(dist<=2.2)
    groove=core|binary_propagation(core,mask=core|((dist<=10)&cut_contrast))
    groove=binary_dilation(groove,iterations=1)
    # Add pre-existing spall pieces connected to the original cut corridor.
    extra=(dist<=18)&strong_cut
    groove|=binary_propagation(groove,mask=groove|extra)
    groove_t=map_coordinates(groove.astype(float),[my,mx],order=0,mode='constant',cval=1)>.5
    inside=cell_labels>0
    eligible=inside&~groove_t&np.isfinite(reg['reference_warped'])
    rw=reg['reference_intensity_matched'].astype(float)
    pred=gaussian_filter(np.nan_to_num(rw,nan=0),.65)
    obs=gaussian_filter(tape,.65)
    dif=obs-pred
    field=np.zeros(tape.shape)
    initial=dif[eligible];med=np.median(initial)
    sigma=max(float(np.median(np.abs(initial-med))*1.4826),1.)
    field[:]=med
    for _ in range(4):
        resid=dif-field
        w=eligible.astype(float)*np.clip(1-(resid/(2.8*sigma))**2,0,1)**2
        sm=gaussian_filter(w,35)
        field=gaussian_filter(np.nan_to_num(dif)*w,35)/np.maximum(sm,.0001)
        residual=dif-field
        vals=residual[eligible];m=np.median(vals)
        sigma=max(float(np.median(np.abs(vals-m))*1.4826),1.)
    expected=pred+field
    z=(obs-expected)/sigma
    am=gaussian_filter(np.maximum(expected,1),12)
    negative_seed=(z<-3.1)&(obs<am*.79)&eligible
    negative_grow=(z<-1.85)&(obs<am*.9)&eligible
    bright_seed=(z>3.8)&(obs>am*1.34)&eligible
    bright_grow=(z>2.0)&(obs>am*1.16)&eligible
    dark=components(negative_grow,negative_seed,5)&eligible
    bright=components(bright_grow,bright_seed,5)&eligible
    loss=(dark|bright)&eligible
    # A stricter mask is retained to expose dependence on the detection threshold.
    strict_dark=components((z<-2.6)&(obs<am*.85)&eligible,(z<-4.0)&(obs<am*.72)&eligible,7)&eligible
    strict_bright=components((z>2.8)&(obs>am*1.25)&eligible,(z>4.8)&(obs>am*1.5)&eligible,7)&eligible
    strict=(strict_dark|strict_bright)&loss
    per=[]
    for n in range(81):
        region=cell_labels==n+1;area=int(np.sum(region&eligible));lost=int(np.sum(region&loss));slost=int(np.sum(region&strict))
        per.append({'cell':n,'row':n//9+1,'column':n%9+1,'total_cell_px':int(np.sum(region)),'groove_excluded_px':int(np.sum(region&groove_t)),
            'eligible_am_px':area,'loss_px':lost,'intact_px':area-lost,'strict_loss_px':slost,'bright_loss_px':int(np.sum(region&bright)),
            'dark_pit_loss_px':int(np.sum(region&dark)),'loss_fraction':lost/area if area else None,
            'status':'Excluded' if area==0 else ('Damaged' if lost else 'No detected loss')})
    total=int(np.sum(eligible));lost=int(np.sum(loss));strictlost=int(np.sum(strict))
    record={'image':i,'columns':9,'rows':9,'total_cells':81,'no_detected_loss_cells':sum(c['status']=='No detected loss' for c in per),
        'damaged_cells':sum(c['status']=='Damaged' for c in per),'excluded_cells':sum(c['status']=='Excluded' for c in per),
        'eligible_am_px':total,'loss_px':lost,'intact_px':total-lost,'groove_excluded_px':int(np.sum(inside&groove_t)),
        'loss_fraction':lost/total,'intact_fraction':1-lost/total,'strict_loss_fraction':strictlost/total,
        'bright_loss_fraction':float(np.sum(bright))/total,'dark_pit_loss_fraction':float(np.sum(dark))/total,
        'noise_sigma_raw':sigma,'per_cell':per}
    metrics.append(record)
    np.savez_compressed(ANA/f'segmentation_{i}.npz',labels=cell_labels,eligible=eligible,grooves=groove_t&inside,loss=loss,strict_loss=strict,
        bright=bright,dark=dark,z=z.astype('float32'),local_prediction=expected.astype('float32'))
    base=np.array(Image.open(ANA/f'taped_display_{i}.png').convert('RGB'))
    result=base.copy();result[loss]=(base[loss]*.25+np.array([90,205,255])*.75).astype('uint8')
    Image.fromarray(result).save(ANA/f'loss_preview_{i}.png')
    diagnostic=base.copy();diagnostic[groove_t&inside]=(255,40,70)
    Image.fromarray(diagnostic).save(ANA/f'groove_preview_{i}.png')
    print(json.dumps({k:v for k,v in record.items() if k!='per_cell'}),flush=True)
(ANA/'segmentation_results.json').write_text(json.dumps(metrics,indent=2))
