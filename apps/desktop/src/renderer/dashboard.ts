import type {Json,WireFrame} from '../core';
import {defaultRuntimeConfig} from './runtime-config.ts';
export const classNames=['Unknown','Car','Bicycle','Motorcycle','Truck','Other vehicle','Person','Bicyclist','Motorcyclist','Road','Parking','Sidewalk','Other ground','Building','Fence','Vegetation','Trunk','Terrain','Pole','Traffic sign'];
export const datasetFormats=[['generic','Generic manifest'],['semanticposs','SemanticPOSS'],['semantickitti','SemanticKITTI'],['rellis3d','RELLIS-3D']] as const;
export interface DashboardEvent {time:number;message:string;kind:string}
export function defaultSessionConfig():Json{return defaultRuntimeConfig();}
export function evidenceAvailable(value:unknown){return typeof value==='string'&&value.length>0&&!['unavailable','disabled','skipped','invalid'].includes(value);}
export function profileConfig(current:Json,name:string):Json{
 if(name==='LowResource'){const low=defaultRuntimeConfig();return {...current,preset:name,map:{...current.map,...low.map},playback:{...current.playback,...low.playback},visualization:low.visualization};}
 const profiles:Record<string,Json>={Performance:{resource_profile:'performance',visualization:{point_budget:20000,cell_budget:10000,update_hz:10}},Balanced:{resource_profile:'balanced',visualization:{point_budget:50000,cell_budget:20000,update_hz:15}},Quality:{resource_profile:'quality',visualization:{point_budget:100000,cell_budget:50000,update_hz:30}}};
 const selected=profiles[name]??profiles.Balanced;
 return {...current,preset:name,map:{...(current.map??{}),resource_profile:selected.resource_profile,governor_override:'automatic'},visualization:selected.visualization};
}
export function layerUnavailable(frame:WireFrame|null,mode:string){return ['ground','terrain','motion','utility','semantic'].includes(mode)&&!evidenceAvailable(frame?.metadata.layers?.[mode]);}
export function perceptionStages(frame:WireFrame|null){
 const status=frame?.metadata.pipeline_status??{};
 const timings=frame?.metadata.perception_timings_ms??{};
 return [['Semantic','semantic'],['Ground','ground'],['Terrain','terrain'],['Temporal','temporal']].map(([label,key])=>({label,status:status[key]??'unavailable',latency:typeof timings[key]==='number'?timings[key]:null}));
}
export function mapActivity(telemetry:Json):[string,unknown][]{return [['Active cells',telemetry.map?.active_cells],['Logical bytes',telemetry.map?.logical_bytes],['Allocated bytes',telemetry.map?.allocated_bytes],['Topology changes',telemetry.map?.topology_changes],['Splits / second',telemetry.map?.splits_per_second],['Merges / second',telemetry.map?.merges_per_second]];}
export const MEMORY_DOMAIN_NOTE='Live process RSS (OS), map logical/allocated bytes (C++ snapshot), and benchmark peak RSS (harness) measure different domains — do not compare across tables.';
export const FIRST_CPU_SAMPLE_NOTE='First CPU sample after (re)start shows — by construction: CPU% needs two /proc samples.';
export function renderAgeMs(render:Json,now=Date.now()):number|null{
 const t=(render as Json)?.updated_at;
 if(typeof t!=='number'||!Number.isFinite(t))return null;
 const age=now-t;
 if(!Number.isFinite(age)||age<0)return null;
 return age;
}
export function isRenderStale(render:Json,now=Date.now(),maxAgeMs=2500):boolean{
 const hasData=typeof (render as Json)?.fps==='number'||typeof (render as Json)?.latency_ms==='number';
 if(!hasData)return false;
 const age=renderAgeMs(render,now);
 if(age==null)return true;
 return age>maxAgeMs;
}
export function formatRenderAge(render:Json,now=Date.now()):string{
 const age=renderAgeMs(render,now);
 if(age==null)return '—';
 if(age<1000)return `${Math.round(age)} ms ago`;
 return `${(age/1000).toFixed(1)} s ago`;
}
export function inputTargetFps(config:Json,status:Json):number|null{
 const fps=config?.playback?.fps,speed=status?.speed??1;
 if(typeof fps!=='number'||!Number.isFinite(fps)||fps<=0)return null;
 if(typeof speed!=='number'||!Number.isFinite(speed)||speed<=0)return null;
 return fps*speed;
}
// Canonical semantic-source presentation. Ground Truth dataset labels must
// never read as neural inference; neural modes show backend-verified device.
export function semanticDisplay(provider:unknown,model:unknown,execution:unknown,backend:unknown):{source:string;sourceSub:string;neural:string;neuralSub:string;execution:string;executionSub:string}{
 const text=(value:unknown)=>typeof value==='string'&&value&&value!=='unavailable'?String(value).replaceAll('_',' '):'Unavailable';
 if(provider==='Ground Truth')return {source:'DATASET GROUND TRUTH',sourceSub:'dataset labels used directly',neural:'BYPASSED',neuralSub:'model latency not measured',execution:'N/A',executionSub:'no accelerator involved'};
 return {source:text(provider),sourceSub:`neural inference · ${text(backend)}`,neural:model?'ACTIVE':'UNAVAILABLE',neuralSub:text(model),execution:text(execution),executionSub:'backend-verified device only'};
}
// Historical-data marker: stale telemetry values are last measured, never live.
export function lastMeasuredPrefix(isStale:boolean):string{return isStale?'LAST MEASURED · ':'';}
// Canonical benchmark capture states. Warmup exclusion is reported post-hoc
// from the artifact (no live warmup signal exists); never claim COMPLETE
// merely because the runtime paused.
export function measurementDisplay(state:unknown):{label:string;sub:string}{
 if(state==='running')return {label:'MEASURING',sub:'frames processing; warmup excluded per artifact'};
 if(state==='complete')return {label:'COMPLETE',sub:'results below are the last valid measurement window'};
 if(state==='failed')return {label:'FAILED',sub:'see error banner; no valid measurement'};
 return {label:'IDLE',sub:'no measurement running'};
}
// Canonical rolling-percentile sample gates. p95/p99 match the benchmark
// harness tail-reliability rule (nearest-rank tails need >=20/>=100 samples);
// p50 needs >=5. Below gate the UI must show N/A + counts, never the raw tail.
export const MIN_SAMPLES={p50:5,p95:20,p99:100} as const;
export function gateStatistic(value:unknown,count:unknown,minimum:number,decimals=1):{ok:boolean;text:string;sub:string}{
 const n=typeof count==='number'&&Number.isFinite(count)?Math.floor(count):0;
 if(typeof value==='number'&&Number.isFinite(value)&&n>=minimum)return {ok:true,text:value.toLocaleString(undefined,{maximumFractionDigits:decimals}),sub:`n = ${n}`};
 return {ok:false,text:'N/A',sub:n>0?`insufficient samples ${n} / ${minimum}`:'no samples yet'};
}
// Canonical processing-state presentation. Never 0 FPS unless measured zero;
// never "—" where the runtime state is known.
export function processingDisplay(status:Json,telemetry:Json):{label:string;sub:string}{
 const state=status?.state;
 if(state==='running'){
  const fps=telemetry?.fps;
  if(typeof fps==='number'&&Number.isFinite(fps))return {label:`${fps.toLocaleString(undefined,{maximumFractionDigits:1})} FPS`,sub:'measuring'};
  return {label:'STARTING',sub:'fewer than 2 completed frames'};
 }
 if(state==='paused')return {label:'PAUSED',sub:'historical values below are last measured'};
 if(state==='error')return {label:'ERROR',sub:'see error banner'};
 if(state==='unconfigured'||state=='stopped'||state==null)return {label:'IDLE',sub:'no session'};
 return {label:String(state).toUpperCase(),sub:'runtime state'};
}
// Configured telemetry publish rate (Hz). A configured cadence, not a measurement.
export function telemetryConfiguredHz(config:Json):number|null{
 const hz=config?.visualization?.update_hz;
 return typeof hz==='number'&&Number.isFinite(hz)&&hz>0?hz:null;
}
export function recordEvent(events:DashboardEvent[],event:Json,now=Date.now()):DashboardEvent[]{
 if(event.type==='diagnostics'){
  const diagnostic=(event.diagnostic??{}) as Json;
  const message=`${diagnostic.code??'Diagnostics'}: ${diagnostic.message??'backend reported a diagnostic'}`;
  if(events.at(-1)?.message===message)return events;
  return [...events,{time:now,message,kind:'error'}].slice(-200);
 }
 if(!['status','benchmark','validation','governor'].includes(event.type))return events;
 const message=event.error?`${event.error.process??'Runtime'}: ${event.error.message??event.error}`:event.type==='benchmark'?`Benchmark ${event.state}`:event.type==='validation'?`Validation ${event.state}`:event.type==='governor'?`Governor: ${event.state??event.mode}`:`Runtime ${event.state}${event.sequence?' · '+event.sequence:''}${typeof event.index==='number'?' · frame '+event.index:''}`;
 if(events.at(-1)?.message===message)return events;
 return [...events,{time:now,message,kind:event.error?'error':event.type}].slice(-200);
}
export function comparisonMetrics(report:Json|null){
 const p=(report?.mapping??report)?.policies;
 const uniform=p?.uniform5?.aggregate,adaptive=(p?.utility_lod??p?.distance_lod)?.aggregate;
 const memoryUniform=uniform?.peak_rss_bytes??null,memoryAdaptive=adaptive?.peak_rss_bytes??null;
 const latencyUniform=uniform?.stage_latency_ns?.map_update?.p95,latencyAdaptive=adaptive?.stage_latency_ns?.map_update?.p95;
 return {memoryUniform,memoryAdaptive,memoryReduction:typeof memoryUniform==='number'&&memoryUniform>0&&typeof memoryAdaptive==='number'?(1-memoryAdaptive/memoryUniform)*100:null,latencyUniform:typeof latencyUniform==='number'?latencyUniform/1e6:null,latencyAdaptive:typeof latencyAdaptive==='number'?latencyAdaptive/1e6:null,adaptivePolicy:p?.utility_lod?'Utility LOD':'Distance LOD'};
}
export function summarizeVisual(frame:WireFrame|null){
 if(!frame||!evidenceAvailable(frame.metadata.layers?.semantic))return [];
 const section=frame.metadata.points,data=new DataView(frame.payload.buffer,frame.payload.byteOffset,frame.payload.byteLength),counts=new Map<number,number>();
 for(let i=0;i<section.count;i++){const id=data.getFloat32(section.offset+i*section.stride+16,true);counts.set(id,(counts.get(id)??0)+1);}
 return [...counts].map(([id,count])=>({id,name:classNames[id]??`Class ${id}`,count,percent:100*count/section.count})).sort((a,b)=>b.count-a.count);
}
export const RENDER_CAPACITY=100000;
export function clampRenderCounts(pointCount:unknown,cellCount:unknown,capacity=RENDER_CAPACITY){
 const clamp=(value:unknown)=>{
  if(typeof value!=='number'||!Number.isFinite(value))return {count:0,truncated:true};
  const count=Math.max(0,Math.floor(value));
  return count>capacity?{count:capacity,truncated:true}:{count,truncated:false};
 };
 const points=clamp(pointCount),cells=clamp(cellCount);
 return {points, cells, truncated:points.truncated||cells.truncated};
}
