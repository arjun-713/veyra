import type {WireFrame} from '../core';

const neutral:[number,number,number]=[.35,.4,.45];
export const levelColors:[number,number,number][]=[[.2,.85,.95],[.3,.85,.5],[1,.7,.25],[.85,.4,.85]];
export function displayPosition(x:number,y:number,z:number){return [y,z,-x];}
function elevation(z:number):[number,number,number]{const t=Math.max(0,Math.min(1,(z+3)/8));return [.2+t*.75,.8-t*.35,.95-t*.7];}
function semantic(id:number):[number,number,number]{
 const palette=[[.35,.4,.45],[.95,.3,.38],[.96,.67,.14],[.96,.67,.14],[.95,.3,.38],[.95,.3,.38],[.64,.34,.93],[.64,.34,.93],[.64,.34,.93],[.22,.55,.98],[.44,.53,.81],[.56,.66,.83],[.72,.58,.43],[.48,.54,.62],[.64,.63,.71],[.22,.7,.3],[.48,.6,.31],[.38,.68,.34],[.96,.67,.14],[.9,.72,.34]];
 return (palette[id]??neutral) as [number,number,number];
}
export function pointColor(mode:string,p:ArrayLike<number>,layers:Record<string,string>):[number,number,number]{
 if(mode==='semantic')return layers.semantic&&layers.semantic!=='unavailable'?semantic(p[4]):neutral;
 if(mode==='elevation')return elevation(p[2]);
 if(mode==='ground')return layers.ground==='available'?(p[5]>.5?[.3,.8,.5]:[.8,.55,.3]):neutral;
 if(mode==='terrain')return layers.terrain==='available'?(p[6]===1?[.2,.85,.5]:p[6]===2?[.95,.3,.35]:neutral):neutral;
 if(mode==='motion')return layers.motion==='available'?[Math.max(.2,p[7]),.4,.7*(1-p[7])]:neutral;
 return [.72,.76,.8];
}
export function cellColor(mode:string,p:ArrayLike<number>):[number,number,number]{
 if(mode==='lod')return levelColors[Math.max(0,Math.min(3,Math.round(Math.log2(p[3]/.05))))];
 if(mode==='semantic')return semantic(p[4]);if(mode==='motion')return [Math.max(.2,p[5]),.4,.7*(1-p[5])];
 if(mode==='terrain')return p[7]>.65?[.2,.85,.5]:p[7]<.35?[.95,.3,.35]:neutral;
 if(mode==='utility'){const u=Math.max(0,Math.min(1,p[8]));return [.15+.8*u,.75*(1-u)+.18,.95-.7*u];}return elevation(p[2]);
}

export interface FallbackMark {
 kind:'point'|'cell';
 sourceIndex:number;
 x:number;
 y:number;
 size:number;
 color:string;
}

export interface FallbackScene {
 marks:FallbackMark[];
 bounds:{minX:number;maxX:number;minY:number;maxY:number};
}

function cssColor(value:[number,number,number]){
 return `rgb(${value.map(channel=>Math.round(Math.max(0,Math.min(1,channel))*255)).join(' ')})`;
}

function fallbackPosition(x:number,y:number,z:number,view:string):[number,number]{
 if(view==='top')return [y,x];
 if(view==='driver')return [y,z-x*.04];
 return [y-x*.28,z+x*.18];
}

function sampledIndices(count:number,budget:number){
 if(count<=0||budget<=0)return [];
 const shown=Math.min(count,budget);
 if(shown===1)return [0];
 return Array.from({length:shown},(_,index)=>Math.round(index*(count-1)/(shown-1)));
}

/** Build a deterministic, bounded 2D view using only values present in a wire frame. */
export function fallbackScene(frame:WireFrame|null,mode:string,showPoints:boolean,showCells:boolean,view:string,maxMarks=25000):FallbackScene{
 const marks:FallbackMark[]=[];
 if(frame&&maxMarks>0){
  const pointCount=showPoints?frame.metadata.points.count:0,cellCount=showCells?frame.metadata.cells.count:0;
  let pointBudget=pointCount,cellBudget=cellCount;
  if(pointCount+cellCount>maxMarks){
   if(pointCount&&cellCount){pointBudget=Math.min(pointCount,Math.floor(maxMarks/2));cellBudget=Math.min(cellCount,maxMarks-pointBudget);pointBudget=Math.min(pointCount,maxMarks-cellBudget);}
   else if(pointCount)pointBudget=maxMarks;
   else cellBudget=maxMarks;
  }
  const data=new DataView(frame.payload.buffer,frame.payload.byteOffset,frame.payload.byteLength);
  for(const index of sampledIndices(pointCount,pointBudget)){
   const offset=frame.metadata.points.offset+index*frame.metadata.points.stride,row=new Float32Array(8);
   for(let field=0;field<8;field++)row[field]=data.getFloat32(offset+field*4,true);
   const [x,y]=fallbackPosition(row[0],row[1],row[2],view);
   marks.push({kind:'point',sourceIndex:index,x,y,size:0,color:cssColor(pointColor(mode,row,frame.metadata.layers??{}))});
  }
  for(const index of sampledIndices(cellCount,cellBudget)){
   const offset=frame.metadata.cells.offset+index*frame.metadata.cells.stride,row=new Float32Array(9);
   for(let field=0;field<9;field++)row[field]=data.getFloat32(offset+field*4,true);
   const [x,y]=fallbackPosition(row[0],row[1],row[2],view);
   marks.push({kind:'cell',sourceIndex:index,x,y,size:row[3],color:cssColor(cellColor(mode,row))});
  }
 }
 if(!marks.length)return {marks,bounds:{minX:-1,maxX:1,minY:-1,maxY:1}};
 let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
 for(const mark of marks){minX=Math.min(minX,mark.x);maxX=Math.max(maxX,mark.x);minY=Math.min(minY,mark.y);maxY=Math.max(maxY,mark.y);}
 if(maxX-minX<1e-6){minX-=1;maxX+=1;}if(maxY-minY<1e-6){minY-=1;maxY+=1;}
 return {marks,bounds:{minX,maxX,minY,maxY}};
}
