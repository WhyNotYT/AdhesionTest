from pathlib import Path
import json, os
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi, signal, optimize

ROOT = Path(os.environ.get('S13_PROJECT_ROOT',str(Path(__file__).resolve().parents[1])))
WORK = ROOT/'work'

def read_raw(kind, idx):
    return np.asarray(Image.open(ROOT/'upload'/f'S13_{kind}_[{idx}].tif'), dtype=np.float32)

def display(a):
    return np.uint8(np.clip(np.sqrt(np.maximum(a,0)/1023)*255,0,255))

def ncc_match(ref, target, x, y, radius=25, search=65):
    x,y=int(x),int(y)
    template=ref[y-radius:y+radius+1,x-radius:x+radius+1].copy()
    if template.shape != (2*radius+1,)*2: return None
    template-=template.mean()
    xl,yl=max(0,x-radius-search),max(0,y-radius-search)
    xr,yr=min(target.shape[1],x+radius+search+1),min(target.shape[0],y+radius+search+1)
    field=target[yl:yr,xl:xr]
    if field.shape[0]<template.shape[0] or field.shape[1]<template.shape[1]: return None
    corr=signal.fftconvolve(field,template[::-1,::-1],mode='valid')
    sums=signal.fftconvolve(field,np.ones(template.shape),mode='valid')
    sums2=signal.fftconvolve(field*field,np.ones(template.shape),mode='valid')
    den=np.sqrt(np.maximum(sums2-sums*sums/template.size,1e-10)*np.sum(template*template))
    corr=corr/den
    iy,ix=np.unravel_index(np.argmax(corr),corr.shape)
    dx=dy=0.
    if 0<ix<corr.shape[1]-1:
        a,b,c=corr[iy,ix-1:ix+2];dx=.5*(a-c)/(a-2*b+c)
    if 0<iy<corr.shape[0]-1:
        a,b,c=corr[iy-1:iy+2,ix];dy=.5*(a-c)/(a-2*b+c)
    return [x,y,xl+ix+radius+dx,yl+iy+radius+dy,float(corr[iy,ix])]

def transform_xy(xy, matrix):
    return np.column_stack([xy,np.ones(len(xy))]) @ matrix.T

def registration(idx):
    r,t=read_raw('Squared',idx),read_raw('Taped',idx)
    rr=np.log(np.maximum(r,8));tt=np.log(np.maximum(t,8))
    # Preserve the stable texture, remove broad exposure/illumination differences.
    rr=ndi.gaussian_filter(rr,.6)-ndi.gaussian_filter(rr,7)
    tt=ndi.gaussian_filter(tt,.6)-ndi.gaussian_filter(tt,7)
    matches=[]
    for y in range(125,981,75):
        for x in range(300,1251,75):
            m=ncc_match(rr,tt,x,y)
            if m and m[4]>.45: matches.append(m)
    matches=np.array(matches)
    xy=matches[:,:2];obs=matches[:,2:4]
    X=np.column_stack([xy,np.ones(len(xy))])
    initial=np.linalg.lstsq(X,obs,rcond=None)[0].T
    res=optimize.least_squares(lambda p:(transform_xy(xy,p.reshape(2,3))-obs).ravel(),initial.ravel(),loss='soft_l1',f_scale=.6,max_nfev=100)
    matrix=res.x.reshape(2,3)
    errors=np.linalg.norm(transform_xy(xy,matrix)-obs,axis=1)
    inliers=(errors<2.5)&(matches[:,4]>.55)
    matrix=np.linalg.lstsq(X[inliers],obs[inliers],rcond=None)[0].T
    errors=np.linalg.norm(transform_xy(xy,matrix)-obs,axis=1)
    yy,xx=np.indices(r.shape)
    tx=matrix[0,0]*xx+matrix[0,1]*yy+matrix[0,2]
    ty=matrix[1,0]*xx+matrix[1,1]*yy+matrix[1,2]
    aligned=ndi.map_coordinates(t,[ty,tx],order=1,mode='constant',cval=np.nan)
    np.savez_compressed(WORK/f'S13_Registration_{idx}.npz',reference=r,taped=t,aligned=aligned,matrix=matrix,matches=matches,inliers=inliers,errors=errors)
    Image.fromarray(display(np.nan_to_num(aligned))).save(WORK/f'S13_Taped_{idx}_Aligned.png')
    # A red/cyan comparison highlights incorrect edge registration.
    rd=display(r);td=display(np.nan_to_num(aligned));checker=np.stack([rd,td,td],axis=2)
    Image.fromarray(checker).save(WORK/f'S13_Registration_{idx}_QC.png')
    result={'image':idx,'matrix_ref_to_taped':matrix.tolist(),'matches':len(matches),'inliers':int(inliers.sum()),'median_error_px':float(np.median(errors[inliers])),'p95_error_px':float(np.percentile(errors[inliers],95)),'median_ncc':float(np.median(matches[inliers,4]))}
    print(json.dumps(result),flush=True)
    return result

def taped_profiles(idx):
    a=read_raw('Taped',idx)
    # Independently observe the cut projections, before consulting Step-1 geometry.
    l=np.log(np.maximum(a,8))
    vert=np.abs(ndi.gaussian_filter(l,(2,.6))-ndi.gaussian_filter(l,(2,4)))
    horiz=np.abs(ndi.gaussian_filter(l,(.6,2))-ndi.gaussian_filter(l,(4,2)))
    vp=ndi.gaussian_filter1d(np.mean(vert[160:895,:],axis=0),1)
    hp=ndi.gaussian_filter1d(np.mean(horiz[:,380:1170],axis=1),1)
    xs,_=signal.find_peaks(vp[320:1210],distance=60,prominence=.004)
    ys,_=signal.find_peaks(hp[80:960],distance=60,prominence=.004)
    peaks={'image':idx,'observed_vertical_peaks':(xs+320).tolist(),'observed_horizontal_peaks':(ys+80).tolist()}
    print(json.dumps(peaks),flush=True)
    return peaks

if __name__=='__main__':
    profiles=[taped_profiles(i) for i in range(1,5)]
    results=[registration(i) for i in range(1,5)]
    (WORK/'S13_Registration_Diagnostics.json').write_text(json.dumps({'profiles':profiles,'registration':results},indent=2))
