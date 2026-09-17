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
export function layerUnavailable(frame:WireFrame|null,mode:string){return ['ground','terrain','motion','utility'].includes(mode)&&!evidenceAvailable(frame?.metadata.layers?.[mode]);}
export function perceptionStages(frame:WireFrame|null){
 const status=frame?.metadata.pipeline_status??{};
 const timings=frame?.metadata.perception_timings_ms??{};
 return [['Semantic','semantic'],['Ground','ground'],['Terrain','terrain'],['Temporal','temporal']].map(([label,key])=>({label,status:status[key]??'unavailable',latency:typeof timings[key]==='number'?timings[key]:null}));
}
export function mapActivity(telemetry:Json):[string,unknown][]{return [['Active cells',telemetry.map?.active_cells],['Logical bytes',telemetry.map?.logical_bytes],['Allocated bytes',telemetry.map?.allocated_bytes],['Topology changes',telemetry.map?.topology_changes],['Splits / second',telemetry.map?.splits_per_second],['Merges / second',telemetry.map?.merges_per_second]];}
export function recordEvent(events:DashboardEvent[],event:Json,now=Date.now()):DashboardEvent[]{
 if(!['status','benchmark','governor'].includes(event.type))return events;
 const message=event.error?`${event.error.process??'Runtime'}: ${event.error.message??event.error}`:event.type==='benchmark'?`Benchmark ${event.state}`:event.type==='governor'?`Governor: ${event.state??event.mode}`:`Runtime ${event.state}${event.sequence?' · '+event.sequence:''}${typeof event.index==='number'?' · frame '+event.index:''}`;
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
