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
