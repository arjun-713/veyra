// Pure viewport maths for MapCanvas: drawable-size guarding and camera
// presets fitted to the map's extent. Kept free of three.js so it is unit
// tested under node; all positions are display (three.js, y-up) coordinates.

export type Vec3=[number,number,number];
export interface Bounds {min:Vec3;max:Vec3}
export interface CameraPose {target:Vec3;position:Vec3}

// A host that has not been laid out (hidden workspace, first mount before
// layout) reports 0x0; sizing the renderer to it gives a 0-pixel canvas and a
// NaN aspect. Returns the size to apply, or null when it must be skipped.
export function drawableSize(width:number,height:number):{width:number;height:number}|null {
 if(!Number.isFinite(width)||!Number.isFinite(height))return null;
 const w=Math.floor(width),h=Math.floor(height);
 return w>=1&&h>=1?{width:w,height:h}:null;
}

// Bounds of `count` rows of `stride` floats whose first three are world
// (x,y,z); converted to display (x,z,-y). One pass, NaN/inf rows skipped.
// Called only when a camera fit is requested (first frame, preset change),
// never per rendered frame.
export function worldRowBounds(rows:ArrayLike<number>,count:number,stride:number):Bounds|null {
 let x0=Infinity,y0=Infinity,z0=Infinity,x1=-Infinity,y1=-Infinity,z1=-Infinity;
 for(let i=0;i<count;i++){
  const o=i*stride,x=rows[o],y=rows[o+2],z=-rows[o+1];
  if(!Number.isFinite(x)||!Number.isFinite(y)||!Number.isFinite(z))continue;
  if(x<x0)x0=x;if(x>x1)x1=x;if(y<y0)y0=y;if(y>y1)y1=y;if(z<z0)z0=z;if(z>z1)z1=z;
 }
 return x0<=x1?{min:[x0,y0,z0],max:[x1,y1,z1]}:null;
}

export const MIN_FIT_DISTANCE=12;
export const MAX_FIT_DISTANCE=400;
const ORBIT_DIRECTION:Vec3=[-32,25,36];
const DRIVER_OFFSET:Vec3=[0,3,8];

const clamp=(v:number,lo:number,hi:number)=>Math.max(lo,Math.min(hi,v));
const tanHalf=(fovDeg:number)=>Math.tan(fovDeg*Math.PI/360);

// Distance at which a perspective camera looking straight down sees the
// whole XZ footprint of `bounds` with a margin.
export function topFitDistance(bounds:Bounds,fovDeg:number,aspect:number,margin=1.15):number {
 const hx=(bounds.max[0]-bounds.min[0])/2,hz=(bounds.max[2]-bounds.min[2])/2,t=tanHalf(fovDeg);
 const a=Number.isFinite(aspect)&&aspect>0?aspect:1;
 const d=Math.max(hz/t,hx/(t*a))*margin+(bounds.max[1]-bounds.min[1]);
 return clamp(Number.isFinite(d)?d:MIN_FIT_DISTANCE,MIN_FIT_DISTANCE,MAX_FIT_DISTANCE);
}

// Distance at which the bounding sphere of `bounds` fits the narrower FOV.
// The map is flat, so the sphere is loose; the default margin tightens it.
export function sphereFitDistance(bounds:Bounds,fovDeg:number,aspect:number,margin=.85):number {
 const dx=bounds.max[0]-bounds.min[0],dy=bounds.max[1]-bounds.min[1],dz=bounds.max[2]-bounds.min[2];
 const radius=Math.hypot(dx,dy,dz)/2,t=tanHalf(fovDeg),a=Number.isFinite(aspect)&&aspect>0?aspect:1;
 const half=Math.atan(t*Math.min(1,a));
 const d=radius/Math.sin(half)*margin;
 return clamp(Number.isFinite(d)?d:MIN_FIT_DISTANCE,MIN_FIT_DISTANCE,MAX_FIT_DISTANCE);
}

export function boundsCenter(bounds:Bounds):Vec3 {
 return [(bounds.min[0]+bounds.max[0])/2,(bounds.min[1]+bounds.max[1])/2,(bounds.min[2]+bounds.max[2])/2];
}

// Camera pose for a preset. Orbit and top frame the map extent; driver stays
// a chase view behind the vehicle. Without bounds the historical fixed
// offsets around `fallbackTarget` are used.
export function presetPose(view:string,bounds:Bounds|null,fovDeg:number,aspect:number,fallbackTarget:Vec3,vehicle:Vec3|null=null):CameraPose {
 if(view==='driver'){
  const t=vehicle??fallbackTarget;
  return {target:[...t],position:[t[0]+DRIVER_OFFSET[0],t[1]+DRIVER_OFFSET[1],t[2]+DRIVER_OFFSET[2]]};
 }
 const target:Vec3=bounds?boundsCenter(bounds):[...fallbackTarget];
 if(view==='top'){
  const d=bounds?topFitDistance(bounds,fovDeg,aspect):100;
  // A tiny z offset keeps OrbitControls' polar angle off the singularity.
  return {target,position:[target[0],target[1]+d,target[2]+.01]};
 }
 const len=Math.hypot(...ORBIT_DIRECTION),d=bounds?sphereFitDistance(bounds,fovDeg,aspect):len;
 return {target,position:[target[0]+ORBIT_DIRECTION[0]/len*d,target[1]+ORBIT_DIRECTION[1]/len*d,target[2]+ORBIT_DIRECTION[2]/len*d]};
}
