from pathlib import Path
import json
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from scipy.ndimage import gaussian_filter, map_coordinates
from scipy.signal import fftconvolve
from scipy.optimize import least_squares

import os
ROOT=Path(os.environ.get('S16_WORK_DIR', Path.cwd()))
ANA=ROOT/'analysis';ANA.mkdir(exist_ok=True)

def structure(a):
    a=a.astype(float)
    high=gaussian_filter(a,.7)-gaussian_filter(a,7)
    rms=np.sqrt(gaussian_filter(high*high,13)+1)
    return np.clip(high/rms,-4,4)

def match(template,search):
    t=template-template.mean();shape=t.shape
    sm=fftconvolve(search,np.ones(shape),mode='valid')
    sq=fftconvolve(search*search,np.ones(shape),mode='valid')
    den=np.sqrt(np.maximum(sq-sm*sm/t.size,1e-8)*np.sum(t*t))
    c=fftconvolve(search,t[::-1,::-1],mode='valid')/den
    iy,ix=np.unravel_index(np.argmax(c),c.shape)
    dx=dy=0.
    if 0<ix<c.shape[1]-1:
        denx=c[iy,ix-1]-2*c[iy,ix]+c[iy,ix+1]
        if denx<0:dx=float(np.clip(.5*(c[iy,ix-1]-c[iy,ix+1])/denx,-.5,.5))
    if 0<iy<c.shape[0]-1:
        deny=c[iy-1,ix]-2*c[iy,ix]+c[iy+1,ix]
        if deny<0:dy=float(np.clip(.5*(c[iy-1,ix]-c[iy+1,ix])/deny,-.5,.5))
    return ix+dx,iy+dy,float(c[iy,ix])

def model_features(points,order=1):
    x=(points[:,0]-750)/500;y=(points[:,1]-540)/500
    if order==1:return np.column_stack([np.ones(len(points)),x,y])
    return np.column_stack([np.ones(len(points)),x,y,x*x,x*y,y*y])

def fit_map(matches,order=1):
    p=matches[:,:2];q=matches[:,2:4]
    b=model_features(p,order)
    sol=np.linalg.lstsq(b,q-p,rcond=None)[0]
    fit=least_squares(lambda v:((b@v.reshape(-1,2)-(q-p))*np.sqrt(matches[:,4,None])).ravel(),sol.ravel(),loss='soft_l1',f_scale=.7)
    sol=fit.x.reshape(-1,2)
    resid=np.sqrt(np.sum((b@sol-(q-p))**2,axis=1))
    keep=resid<2.5
    if np.sum(keep)>len(sol)*3:
        sol=np.linalg.lstsq(b[keep]*matches[keep,4,None],(q-p)[keep]*matches[keep,4,None],rcond=None)[0]
    resid=np.sqrt(np.sum((b@sol-(q-p))**2,axis=1))
    return sol,resid

def transform(points,sol):
    return points+model_features(points,1 if len(sol)==3 else 2)@sol

def inverse_map(sol):
    yy,xx=np.indices((1080,1440),float)
    p=np.column_stack((xx.ravel(),yy.ravel()));q=p.copy()
    for _ in range(6):q+=p-transform(q,sol)
    return q[:,1].reshape(1080,1440),q[:,0].reshape(1080,1440)

def display(a):
    lo,hi=np.percentile(a,[.1,99.5])
    return np.uint8(np.clip((a-lo)/(hi-lo),0,1)**.8*255)

results=[]
for i in range(1,5):
    ref=np.asarray(Image.open(ROOT/'references'/f'S16_Squared_[{i}].tif')).astype(float)
    tape=np.asarray(Image.open(ROOT/'upload'/f'S16_Taped_[{i}].tif')).astype(float)
    Image.fromarray(display(tape)).save(ANA/f'taped_display_{i}.png')
    a=structure(ref);b=structure(tape)
    matches=[];half=30;search=25
    for y in range(190,901,65):
        for x in range(390,1131,65):
            cx=x+24;cy=y-5
            t=a[y-half:y+half+1,x-half:x+half+1]
            s=b[cy-half-search:cy+half+search+1,cx-half-search:cx+half+search+1]
            dx,dy,c=match(t,s)
            if c>.25:matches.append([x,y,cx-search+dx,cy-search+dy,c])
    matches=np.array(matches)
    affine,ar=fit_map(matches,1)
    good=matches[ar<3]
    quadratic,qr=fit_map(good,2)
    yy,xx=inverse_map(quadratic)
    aw=map_coordinates(a,[yy,xx],order=1,mode='nearest')
    # Refine with larger templates after initial geometric alignment.
    refinements=[];half=38;search=6
    for y in range(200,901,62):
        for x in range(410,1131,62):
            t=aw[y-half:y+half+1,x-half:x+half+1]
            s=b[y-half-search:y+half+search+1,x-half-search:x+half+search+1]
            dx,dy,c=match(t,s)
            if c>.3:
                orig=np.array([map_coordinates(xx,[[y],[x]],order=1)[0],map_coordinates(yy,[[y],[x]],order=1)[0]])
                refinements.append([orig[0],orig[1],x-search+dx,y-search+dy,c])
    refined=np.array(refinements)
    quadratic,rr=fit_map(refined,2)
    yy,xx=inverse_map(quadratic)
    warped=map_coordinates(ref,[yy,xx],order=1,mode='constant',cval=np.nan)
    # Robust per-pair linear intensity matching for inspection only.
    interior=np.zeros(ref.shape,bool);interior[190:890,410:1130]=True
    ok=interior&np.isfinite(warped)
    p=np.column_stack((warped[ok],np.ones(np.sum(ok))));q=tape[ok]
    coeff=np.linalg.lstsq(p[::10],q[::10],rcond=None)[0]
    for _ in range(6):
        r=q-p@coeff; med=np.median(r);mad=np.median(np.abs(r-med))*1.4826
        keep=np.abs(r-med)<1.7*mad
        coeff=np.linalg.lstsq(p[keep][::8],q[keep][::8],rcond=None)[0]
    norm=warped*coeff[0]+coeff[1]
    np.savez_compressed(ANA/f'registration_{i}.npz',map_y=yy.astype('float32'),map_x=xx.astype('float32'),reference_warped=warped.astype('float32'),reference_intensity_matched=norm.astype('float32'),matches=refined,residuals=rr,coefficients=quadratic)
    result={'pair':i,'initial_match_count':len(matches),'refined_match_count':len(refined),'inlier_match_count':int(np.sum(rr<2.5)),
        'median_residual_px':float(np.median(rr[rr<2.5])),'p95_residual_px':float(np.percentile(rr[rr<2.5],95)),
        'quadratic_displacement_coefficients':quadratic.tolist(),'photometric_gain':float(coeff[0]),'photometric_offset':float(coeff[1]),
        'transform_model':'reference to taped: p + [1,(x-750)/500,(y-540)/500,xn^2,xn*yn,yn^2] @ coefficients'}
    results.append(result)
    print(json.dumps(result),flush=True)
    # Full-size side-by-side diagnostics in identical taped intensity units.
    low,high=np.percentile(tape,[.1,99.5]);gamma=.8
    def show(v):return Image.fromarray(np.uint8(np.nan_to_num(np.clip((v-low)/(high-low),0,1))**gamma*255)).convert('RGB')
    canvas=Image.new('RGB',(2880,1120),'white');canvas.paste(show(norm),(0,40));canvas.paste(show(tape),(1440,40))
    dr=ImageDraw.Draw(canvas);dr.text((15,15),f'S16 pair {i} | aligned squared reference (intensity matched)',fill='black');dr.text((1455,15),'Taped',fill='black')
    canvas.save(ANA/f'comparison_{i}.jpg',quality=96)
(ANA/'registration_summary.json').write_text(json.dumps(results,indent=2))
