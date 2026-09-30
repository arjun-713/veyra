// Driver-view chase camera math: pure numbers, no three.js, no allocation
// per frame. Heading comes from displacement between successive vehicle
// positions because the sensor x-axis need not align with travel (e.g.
// SemanticPOSS: pose[0]≈-1 while driving along +world y). Output is in
// display coordinates: world (x,y,z) -> display (x,z,-y).
export const CHASE={minMove:.15,back:10,up:4,ahead:6,lookUp:1,rate:6};
export type ChaseState={generation:number;index:number;x:number;y:number;z:number;ax:number;ay:number;hx:number;hy:number};
export const createChaseState=():ChaseState=>({generation:-1,index:-1,x:0,y:0,z:0,ax:0,ay:0,hx:1,hy:0});
export function resetChase(s:ChaseState){s.generation=-1;s.index=-1;}
// Feeds one row-major 4x4 pose. Returns true when the camera must snap
// (first frame, new generation / replay loop, or backwards seek).
export function observePose(s:ChaseState,generation:number,index:number,pose:ArrayLike<number>):boolean{
 const x=pose[3],y=pose[7],z=pose[11];
 const reset=s.generation<0||generation!==s.generation||index<s.index;
 s.generation=generation;s.index=index;s.x=x;s.y=y;s.z=z;
 if(reset){
  s.ax=x;s.ay=y;const fx=pose[0],fy=pose[4],len=Math.hypot(fx,fy);
  if(len>1e-6){s.hx=fx/len;s.hy=fy/len;}
  return true;
 }
 // Displacement from the last anchor, so slow creep still registers while
 // sub-threshold jitter never swings the heading.
 const dx=x-s.ax,dy=y-s.ay,d=Math.hypot(dx,dy);
 if(d>CHASE.minMove){s.hx=dx/d;s.hy=dy/d;s.ax=x;s.ay=y;}
 return false;
}
// out = [camX,camY,camZ, lookX,lookY,lookZ] in display coordinates.
export function chaseTargets(s:ChaseState,out:{[i:number]:number}){
 out[0]=s.x-s.hx*CHASE.back;out[1]=s.z+CHASE.up;out[2]=-(s.y-s.hy*CHASE.back);
 out[3]=s.x+s.hx*CHASE.ahead;out[4]=s.z+CHASE.lookUp;out[5]=-(s.y+s.hy*CHASE.ahead);
}
// Frame-rate independent exponential smoothing factor for dt seconds.
export const chaseAlpha=(dt:number,rate=CHASE.rate)=>dt>0?1-Math.exp(-dt*rate):0;
