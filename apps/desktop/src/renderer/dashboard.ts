import type {Json,WireFrame} from '../core';
export const classNames=['Unknown','Car','Bicycle','Motorcycle','Truck','Other vehicle','Person','Bicyclist','Motorcyclist','Road','Parking','Sidewalk','Other ground','Building','Fence','Vegetation','Trunk','Terrain','Pole','Traffic sign'];
export const datasetFormats=[['generic','Generic manifest'],['semanticposs','SemanticPOSS'],['semantickitti','SemanticKITTI'],['rellis3d','RELLIS-3D']] as const;
export interface DashboardEvent {time:number;message:string;kind:string;signature?:string}
export function evidenceAvailable(value:unknown){return typeof value==='string'&&value!=='unavailable';}
export function profileConfig(current:Json,name:string):Json{
 const profiles:Record<string,Json>={Performance:{resource_profile:'performance',visualization:{point_budget:20000,cell_budget:10000,update_hz:10}},Balanced:{resource_profile:'balanced',visualization:{point_budget:50000,cell_budget:20000,update_hz:15}},Quality:{resource_profile:'quality',visualization:{point_budget:100000,cell_budget:50000,update_hz:30}}};
 const selected=profiles[name]??profiles.Balanced;
 return {...current,map:{...(current.map??{}),resource_profile:selected.resource_profile,governor_override:'automatic'},visualization:selected.visualization};
}
export function layerUnavailable(frame:WireFrame|null,mode:string){return ['ground','terrain','motion','utility'].includes(mode)&&!evidenceAvailable(frame?.metadata.layers?.[mode]);}
export function mapActivity(telemetry:Json):[string,unknown][]{return [['Active cells',telemetry.map?.active_cells],['Logical bytes',telemetry.map?.logical_bytes],['Allocated bytes',telemetry.map?.allocated_bytes],['Topology changes',telemetry.map?.topology_changes],['Splits / second',telemetry.map?.splits_per_second],['Merges / second',telemetry.map?.merges_per_second]];}
function timestampMs(value:unknown){return typeof value==='number'&&Number.isFinite(value)?value>1e12?value:value*1000:null;}
export function metricTrend(samples:Json[],key:string,windowMs=60000){
 const measured=samples.map(sample=>({time:timestampMs(sample.timestamp),value:sample[key]})).filter((sample):sample is {time:number;value:number}=>sample.time!==null&&typeof sample.value==='number'&&Number.isFinite(sample.value));
 if(measured.length<2)return null;
 const latest=measured.at(-1)!;let baseline=measured[0];
 for(const sample of measured){if(sample.time>=latest.time-windowMs){baseline=sample;break;}}
 const covered=latest.time-baseline.time;
 if(covered<Math.min(windowMs*0.75,45000))return null;
 return {delta:latest.value-baseline.value,baseline:baseline.value,current:latest.value,coveredMs:covered};
}
export function governorEvent(previous:Json|null,current:Json|null):Json|null{
 if(!current||current.state==='unavailable')return null;
 const changedState=current.state!==previous?.state;
 const interventions=(current.interventions??0)-(previous?.interventions??0);
 const actions=(current.actions_applied??0)-(previous?.actions_applied??0);
 if(!changedState&&interventions<=0&&actions<=0)return null;
 return {type:'governor',state:current.state,interventions:Math.max(0,interventions),actions:Math.max(0,actions),allow_optional_splits:current.allow_optional_splits};
}
export function recordEvent(events:DashboardEvent[],event:Json,now=Date.now()):DashboardEvent[]{
 if(!['status','benchmark','governor'].includes(event.type))return events;
 const kind=event.error?'error':event.type;
 const signature=event.error?`error:${event.error.process}:${event.error.message}`:event.type==='benchmark'?`benchmark:${event.state}`:event.type==='governor'?`governor:${event.state}:${event.interventions??0}:${event.actions??0}`:`status:${event.state}:${event.sequence??''}:${event.policy??''}`;
 if(events.slice().reverse().find(item=>item.kind===kind)?.signature===signature)return events;
 const message=event.error?`${event.error.process??'Runtime'}: ${event.error.message??event.error}`:event.type==='benchmark'?`Benchmark ${event.state}`:event.type==='governor'?`Governor ${event.state}${event.actions?` · ${event.actions} map merges applied`:event.interventions?' · optional detail constrained':''}`:`Runtime ${event.state}${event.sequence?' · '+event.sequence:''}${event.policy?' · '+String(event.policy).replaceAll('_',' '):''}`;
 return [...events,{time:now,message,kind,signature}].slice(-200);
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
