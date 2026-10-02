// Overview (Dashboard) presentation while Smooth Replay is active. The
// Overview canvases render the same cached frames as the Viewer; every
// metric shown next to them must then come from the replay cache header or
// the frame's RECORDED cache-build telemetry — never from stale live
// telemetry, which keeps its last values underneath while replaying.
import type {Json} from '../core.ts';
import {formatRecorded} from './replay-metrics.ts';

export interface OverviewCard {icon:string;label:string;value:string;unit:string;detail:string}
export interface OverviewSession {title:string;line:string;policy:string|null}

const text=(value:unknown):string|null=>typeof value==='string'&&value?value:null;
const num=(value:number,digits=1)=>value.toLocaleString(undefined,{maximumFractionDigits:digits});
const bytes=(value:number)=>value>=1073741824?`${num(value/1073741824,2)} GB`:`${num(value/1048576,1)} MB`;
const policyText=(value:string|null)=>value?value.replaceAll('_',' '):'No policy';

/** Dataset/sequence identity for the header and Overview: the replay cache
 * header while replaying (a cache can be opened without a live session). */
export function sessionIdentity(status:Json,replay:boolean):{dataset:string|null;sequence:string|null;policy:string|null}{
 const source=replay?status.replay??{}:{};
 return {
  dataset:text(source.dataset)??text(status.dataset),
  sequence:text(source.sequence)??text(status.sequence),
  policy:text(source.policy)??text(status.policy),
 };
}

/** Header scenario chip: never "No dataset selected" while a replay plays. */
export function sessionLabel(status:Json,replay:boolean):string{
 const {dataset,sequence}=sessionIdentity(status,replay);
 if(!sequence)return replay&&dataset?dataset:'No dataset selected';
 return `${dataset??'—'} · ${sequence}`;
}

export function overviewSession(status:Json,replay:boolean,awaitingFrame=false):OverviewSession{
 const {dataset,sequence,policy}=sessionIdentity(status,replay);
 if(!replay){
  const frames=typeof status.frames==='number'&&Number.isFinite(status.frames)?num(status.frames,0):'—';
  return {title:awaitingFrame?'Preparing your preview':dataset??'Current session',line:`Sequence ${sequence??'—'} · ${frames} frames · ${policyText(policy)}`,policy};
 }
 const r=status.replay??{};
 const total=typeof r.frames==='number'&&Number.isFinite(r.frames)?r.frames:status.frames;
 const position=typeof r.position==='number'&&r.position>=0?r.position:typeof status.index==='number'?status.index:null;
 const at=position===null||typeof total!=='number'?'—':`${num(position,0)} / ${num(total,0)}`;
 return {title:dataset??'Smooth replay',line:`Smooth Replay · cached presentation · Sequence ${sequence??'—'} · frame ${at} · ${policyText(policy)}`,policy};
}

/** Metric cards while replaying: RECORDED cache-build values (formatRecorded)
 * or an explicit N/A — the live cards' STARTING / rolling p95 / RSS would
 * otherwise describe a pipeline that is not running. */
export function replayCards(recorded:Json|null|undefined,status:Json):OverviewCard[]{
 const rec=recorded??{};
 const fps=status.replay?.fps;
 return [
  {icon:'speed',label:'Processing · RECORDED',value:formatRecorded(rec.map_metrics?.fps,v=>`${num(v)} FPS`),unit:'',detail:`Measured during cache build — not live throughput${typeof fps==='number'?` · presenting ${num(fps,0)} cached FPS`:''}`},
  {icon:'bolt',label:'Map update · RECORDED',value:formatRecorded(rec.map_update_ms,v=>`${num(v,2)} ms`),unit:'',detail:'C++ map update recorded with this frame'},
  {icon:'chip',label:'Map memory · RECORDED',value:formatRecorded(rec.logical_bytes,bytes),unit:'',detail:'Logical map bytes recorded · process RSS not measured during replay'},
  {icon:'grid',label:'Active Cells · RECORDED',value:formatRecorded(rec.active_cells,v=>num(v,0)),unit:'',detail:'Map leaves recorded with this frame'},
 ];
}

/** Overview Smooth Replay control. Plays/pauses an open replay, or opens the
 * prepared auto-replay cache (or a manual path) and plays it. */
export function replayControl(input:{replayActive:boolean;running:boolean;canOpen:boolean;busy:boolean;canPlay:boolean;autoReplay?:Json|null}):{enabled:boolean;playing:boolean;label:string;hint:string}{
 const {replayActive,running,canOpen,busy,canPlay,autoReplay}=input;
 const playing=replayActive&&running;
 const label=playing?'Pause replay':'Play replay';
 if(busy)return {enabled:false,playing,label,hint:'Opening smooth replay…'};
 if(replayActive)return {enabled:canPlay,playing,label,hint:playing?'Cached snapshots · presentation rate, not processing throughput':'Smooth replay open · paused'};
 const state=autoReplay?.state;
 if(canOpen&&canPlay)return {enabled:true,playing:false,label,hint:state==='ready'&&typeof autoReplay?.frames==='number'?`${num(autoReplay.frames,0)} cached frames ready`:'Replay cache ready'};
 const hint=state==='preparing'?`Preparing smooth replay: ${num(Number(autoReplay?.done??0),0)} / ${num(Number(autoReplay?.frames??0),0)} frames`:state==='pending'?'Preparing smooth replay after preview…':state==='failed'?`Replay preparation failed${autoReplay?.error?`: ${autoReplay.error}`:''}`:'No smooth replay prepared yet';
 return {enabled:false,playing:false,label,hint};
}
