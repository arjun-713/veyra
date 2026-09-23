// Display-only accumulation of recent pose-aligned scans for the raw LiDAR view.
// The mapper still consumes one scan per frame; this history never feeds back.

export const ACCUMULATION_POINT_CAPACITY=2_000_000;
// Compact per-point record: world x,y,z, then the colour inputs pointColor reads
// (semantic id, ground, drivable, motion) so a mode change can recolour history.
export const HISTORY_STRIDE=7;
const WIRE_STRIDE=17;
// Veyra classes 1-8 (car ... motorcyclist) can move between scans. Stacking
// them smears traffic into long trails, so only the live scan keeps them.
export function isDynamicClass(id:number){return id>=1&&id<=8;}

export interface HistoryFrame {index:number;count:number;rows:Float32Array}

export class ScanHistory {
 private frames:HistoryFrame[]=[];
 private key='';
 private lastIndex=-1;
 window:number;capacity:number;
 constructor(window:number,capacity=ACCUMULATION_POINT_CAPACITY){this.window=window;this.capacity=capacity;}

 // Returns true when the retained history changed.
 push(meta:{generation:number;index:number;dataset?:string;sequence?:string;pose_available?:boolean},wire:Float32Array,count:number):boolean{
  const key=`${meta.generation}|${meta.dataset??''}|${meta.sequence??''}`;
  // Sensor-frame scans cannot be aligned, so only world-frame scans accumulate.
  const window=meta.pose_available?Math.max(1,this.window):1;
  if(key!==this.key||meta.index<this.lastIndex){this.frames=[];this.key=key;this.lastIndex=-1;}
  if(meta.index===this.lastIndex&&this.frames.length)return false;
  const rows=new Float32Array(count*HISTORY_STRIDE);
  for(let i=0;i<count;i++){
   const s=i*WIRE_STRIDE,d=i*HISTORY_STRIDE;
   rows[d]=wire[s];rows[d+1]=wire[s+1];rows[d+2]=wire[s+2];
   rows[d+3]=wire[s+4];rows[d+4]=wire[s+6];rows[d+5]=wire[s+7];rows[d+6]=wire[s+12];
  }
  const previous=this.frames.at(-1);
  if(previous)this.frames[this.frames.length-1]=withoutDynamic(previous);
  this.frames.push({index:meta.index,count,rows});
  this.lastIndex=meta.index;
  this.trim(window);
  return true;
 }

 setWindow(window:number){this.window=window;this.trim(Math.max(1,window));}

 private trim(window:number){
  while(this.frames.length>window)this.frames.shift();
  let total=this.frames.reduce((sum,frame)=>sum+frame.count,0);
  while(this.frames.length>1&&total>this.capacity)total-=this.frames.shift()!.count;
 }

 clear(){this.frames=[];this.key='';this.lastIndex=-1;}
 get pointCount(){return this.frames.reduce((sum,frame)=>sum+frame.count,0);}
 get frameCount(){return this.frames.length;}
 // Oldest first, so the newest scan draws last.
 list():readonly HistoryFrame[]{return this.frames;}
}

function withoutDynamic(frame:HistoryFrame):HistoryFrame{
 let kept=0;
 for(let i=0;i<frame.count;i++)if(!isDynamicClass(frame.rows[i*HISTORY_STRIDE+3]))kept++;
 if(kept===frame.count)return frame;
 const rows=new Float32Array(kept*HISTORY_STRIDE);
 for(let i=0,n=0;i<frame.count;i++){
  const o=i*HISTORY_STRIDE;
  if(isDynamicClass(frame.rows[o+3]))continue;
  rows.set(frame.rows.subarray(o,o+HISTORY_STRIDE),n*HISTORY_STRIDE);n++;
 }
 return {index:frame.index,count:kept,rows};
}

// Expand a compact record into the wire-row indices pointColor reads.
export function colorInput(rows:Float32Array,offset:number,scratch:Float32Array){
 scratch[2]=rows[offset+2];scratch[4]=rows[offset+3];scratch[6]=rows[offset+4];scratch[7]=rows[offset+5];scratch[12]=rows[offset+6];
 return scratch;
}
