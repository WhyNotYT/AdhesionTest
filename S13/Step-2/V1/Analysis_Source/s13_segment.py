from pathlib import Path
import json
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi, optimize
from s13_register import ROOT, WORK, read_raw, display

def components(mask, min_area=3):
    labels,n=ndi.label(mask,np.ones((3,3),dtype=bool))
    areas=np.bincount(labels.ravel())
    keep=areas>=min_area;keep[0]=False
    return keep[labels]

def basis(xx,yy):
    x=(xx-720)/720;y=(yy-540)/540
    return np.stack([np.ones_like(x),x,y,x*x,x*y,y*y],axis=-1)

def mask_in_reference(idx):
    r=read_raw('Squared',idx)
    masks=ROOT/'S13_Step1/Reusable_Grid_Data'
    labels=np.array(Image.open(masks/f'S13_Squared_{idx}_Cell_ID_Mask.tif'))
    cut=np.array(Image.open(masks/f'S13_Squared_{idx}_Boundary_Mask.png'))>0
    distance=ndi.distance_transform_edt(~cut)
    sm=ndi.gaussian_filter(r,.65)
    bg=ndi.gaussian_filter(r,12)
    near=(distance<=6)&(labels>0)
    abnormal=(sm<.67*bg)|(sm>1.6*bg)
    initial=ndi.binary_propagation(cut,mask=cut|(near&abnormal))
    scrape=ndi.binary_dilation(initial,iterations=2)&(labels>0)
    # Only unequivocally bright pre-existing interior exposure is removed here.
    oldfoil=components((sm>2.1*bg)&(sm>250)&(labels>0)&~scrape,3)
    oldfoil=ndi.binary_dilation(oldfoil,iterations=1)&(labels>0)&~scrape
    return labels,scrape,oldfoil

def segment(idx):
    d=np.load(WORK/f'S13_Registration_{idx}.npz')
    r,t=d['reference'],d['taped'];m=d['matrix']
    inv=np.linalg.inv(np.vstack([m,[0,0,1]]))[:2]
    yy,xx=np.indices(t.shape)
    rx=inv[0,0]*xx+inv[0,1]*yy+inv[0,2]
    ry=inv[1,0]*xx+inv[1,1]*yy+inv[1,2]
    coords=[ry,rx]
    rw=ndi.map_coordinates(r,coords,order=1,mode='constant',cval=np.nan)
    lr,sr,fr=mask_in_reference(idx)
    labels=ndi.map_coordinates(lr,coords,order=0,mode='constant',cval=0)
    scrape=ndi.map_coordinates(sr.astype(np.uint8),coords,order=0,mode='constant',cval=0)>0
    oldfoil=ndi.map_coordinates(fr.astype(np.uint8),coords,order=0,mode='constant',cval=0)>0
    valid=(labels>0)&~scrape&~oldfoil&np.isfinite(rw)
    # Very small smoothing suppresses camera noise without deleting small clusters.
    rs=ndi.gaussian_filter(np.nan_to_num(rw,nan=1),.6)
    ts=ndi.gaussian_filter(t,.6)
    logr=np.log(np.maximum(rs,8));logt=np.log(np.maximum(ts,8))
    rawdiff=logt-logr
    core=valid&(ndi.distance_transform_edt(~scrape)>8)
    pts=[];vals=[]
    for cid in range(1,82):
        mask=core&(labels==cid)
        cy,cx=np.nonzero(mask)
        pts.append([cx.mean(),cy.mean()]);vals.append(float(np.median(rawdiff[mask])))
    pts=np.array(pts);vals=np.array(vals)
    X=basis(pts[:,0],pts[:,1])
    p0=np.linalg.lstsq(X,vals,rcond=None)[0]
    fit=optimize.least_squares(lambda p:X@p-vals,p0,loss='soft_l1',f_scale=.04)
    field=np.einsum('ijk,k->ij',basis(xx,yy),fit.x)
    delta=rawdiff-field
    negative=-delta[core&(delta<0)]
    noise=float(np.percentile(negative,68.27))
    # A background map estimated on surviving material, away from tool cuts.
    background_log=ndi.gaussian_filter(np.where(core,logt,0),18)/np.maximum(ndi.gaussian_filter(core.astype(float),18),1e-6)
    bright=logt-background_log
    negative_bright=-bright[core&(bright<0)]
    bright_noise=float(np.percentile(negative_bright,68.27))
    stats={'image':idx,'valid_pixels':int(valid.sum()),'grid_pixels':int((labels>0).sum()),'scrape_pixels':int(scrape.sum()),'oldfoil_pixels':int(oldfoil.sum()),'noise_log_ratio':noise,'noise_log_brightness':bright_noise,'field_coefficients':fit.x.tolist(),'cell_ratio_residual_p95':float(np.percentile(np.abs(X@fit.x-vals),95)),'thresholds':[]}
    # Operational optical thresholds. A brightening ratio alone is insufficient:
    # require both a paired new increase and brightness above the local coating.
    # The high setting deliberately retains faint candidate regions for review.
    for sensitivity,z,ratio in [('High',2.0,1.5),('Moderate',2.5,1.7),('Conservative',3.0,2.0)]:
        dt=max(.22,z*noise);bt=np.log(ratio)
        loss=components(valid&(delta>dt)&(bright>bt),3)
        counts=np.bincount(labels[loss].ravel(),minlength=82)[1:]
        denoms=np.bincount(labels[valid].ravel(),minlength=82)[1:]
        result={'sensitivity':sensitivity,'sigma_multiplier':z,'local_brightness_ratio':ratio,'delta_threshold':dt,'bright_threshold':bt,'loss_pixels':int(loss.sum()),'loss_pct':float(100*loss.sum()/valid.sum()),'damaged_cells':int((counts>0).sum()),'max_cell_loss_pct':float(np.max(100*counts/denoms))}
        stats['thresholds'].append(result)
        # Blue in the actual pixel mask, no dilation for presentation.
        base=np.stack([display(t)]*3,axis=2)
        base[loss]=(.25*base[loss]+.75*np.array([100,205,255])).astype(np.uint8)
        base[scrape]=(.6*base[scrape]+.4*np.array([100,100,100])).astype(np.uint8)
        Image.fromarray(base).save(WORK/f'S13_Taped_{idx}_{sensitivity}_Loss_Draft.png')
        if sensitivity=='High':
            np.savez_compressed(WORK/f'S13_Segmentation_{idx}.npz',reference_aligned=rw,labels=labels,scrape=scrape,oldfoil=oldfoil,valid=valid,loss=loss,delta=delta,brightness=bright,normalization_log=field,delta_threshold=dt,brightness_threshold=bt)
    print(json.dumps(stats),flush=True)
    return stats

if __name__=='__main__':
    results=[segment(i) for i in range(1,5)]
    (WORK/'S13_Segmentation_Diagnostics.json').write_text(json.dumps(results,indent=2))
