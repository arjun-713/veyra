const neutral:[number,number,number]=[.35,.4,.45];
export const levelColors:[number,number,number][]=[[.2,.85,.95],[.3,.85,.5],[1,.7,.25],[.85,.4,.85]];
// World frames are right-handed z-up; three.js is right-handed y-up. (x,z,-y)
// is a proper rotation, so the scene is not mirrored.
export function displayPosition(x:number,y:number,z:number){return [x,z,-y];}
function elevation(z:number):[number,number,number]{const t=Math.max(0,Math.min(1,(z+3)/8));return [.2+t*.75,.8-t*.35,.95-t*.7];}
// Shared lookup storage: semantic replay can color millions of retained
// points per snapshot, so constructing this palette per entity causes GC.
const semanticPalette:[number,number,number][]=[[.35,.4,.45],[.95,.3,.38],[.96,.67,.14],[.96,.67,.14],[.95,.3,.38],[.95,.3,.38],[.64,.34,.93],[.64,.34,.93],[.64,.34,.93],[.22,.55,.98],[.44,.53,.81],[.56,.66,.83],[.72,.58,.43],[.48,.54,.62],[.64,.63,.71],[.22,.7,.3],[.48,.6,.31],[.38,.68,.34],[.96,.67,.14],[.9,.72,.34]];
function semantic(id:number):[number,number,number]{return semanticPalette[id]??neutral;}
export function pointColor(mode:string,p:ArrayLike<number>,layers:Record<string,string>):[number,number,number]{
 if(mode==='semantic')return layers.semantic&&layers.semantic!=='unavailable'?semantic(p[4]):neutral;
 if(mode==='elevation')return elevation(p[2]);
 if(mode==='ground')return !!layers.ground&&!['unavailable','disabled','invalid','skipped'].includes(layers.ground)?(p[6]>.5?[.3,.8,.5]:[.8,.55,.3]):neutral;
 if(mode==='terrain')return layers.terrain==='available'?(p[7]===1?[.2,.85,.5]:p[7]===2?[.95,.3,.35]:neutral):neutral;
 if(mode==='motion')return layers.motion==='available'?[Math.max(.2,p[12]),.4,.7*(1-p[12])]:neutral;
 return [.72,.76,.8];
}
export function cellColor(mode:string,p:ArrayLike<number>):[number,number,number]{ if(mode==='ground')return neutral;
 if(mode==='lod')return levelColors[Math.max(0,Math.min(3,Math.round(Math.log2(p[3]/.05))))];
 if(mode==='semantic')return semantic(p[4]);if(mode==='motion')return [Math.max(.2,p[5]),.4,.7*(1-p[5])];
 if(mode==='terrain'){const e=p[7];if(typeof e!=='number'||!Number.isFinite(e))return neutral;if(e>0)return [.2,.85,.5];if(e<0)return [.95,.3,.35];return neutral;}
 if(mode==='utility'){const u=Math.max(0,Math.min(1,p[8]));return [.15+.8*u,.75*(1-u)+.18,.95-.7*u];}return elevation(p[2]);
}
export function semanticRGB(id:number):[number,number,number]{return semantic(id);}
export function cssRGB(c:[number,number,number]):string{return `rgb(${Math.round(c[0]*255)},${Math.round(c[1]*255)},${Math.round(c[2]*255)})`;}
