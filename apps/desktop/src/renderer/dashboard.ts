import type {Json,WireFrame} from '../core';
export const classNames=['Unknown','Car','Bicycle','Motorcycle','Truck','Other vehicle','Person','Bicyclist','Motorcyclist','Road','Parking','Sidewalk','Other ground','Building','Fence','Vegetation','Trunk','Terrain','Pole','Traffic sign'];
export const datasetFormats=[['generic','Generic manifest'],['semanticposs','SemanticPOSS'],['semantickitti','SemanticKITTI'],['rellis3d','RELLIS-3D']] as const;
export interface DashboardEvent {time:number;message:string;kind:string}
export function defaultSessionConfig():Json{return {dataset:'generic',dataset_root:'',sequence:'',pipeline:{semantic:{mode:'ground_truth'},ground:{enabled:true,parameter_overrides:{min_range:0,max_range:100}},terrain:{enabled:true},temporal:{enabled:false}},map:{policy:'distance_lod',window_radius_m:100.001,resource_profile:'balanced',governor_override:'automatic'},playback:{fps:10,speed:1},visualization:{point_budget:50000,cell_budget:20000,update_hz:15}};}
export function evidenceAvailable(value:unknown){return typeof value==='string'&&value!=='unavailable';}
export function profileConfig(current:Json,name:string):Json{
 const profiles:Record<string,Json>={Performance:{resource_profile:'performance',visualization:{point_budget:20000,cell_budget:10000,update_hz:10}},Balanced:{resource_profile:'balanced',visualization:{point_budget:50000,cell_budget:20000,update_hz:15}},Quality:{resource_profile:'quality',visualization:{point_budget:100000,cell_budget:50000,update_hz:30}}};
 const selected=profiles[name]??profiles.Balanced;
 return {...current,map:{...(current.map??{}),resource_profile:selected.resource_profile,governor_override:'automatic'},visualization:selected.visualization};
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
export function recordEvent(events:DashboardEvent[],event:Json,now=Date.now()):DashboardEvent[]{
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
