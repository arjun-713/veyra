import type {Json,WireFrame} from '../core';
import {defaultRuntimeConfig} from './runtime-config.ts';
import {comparisonScope,qualityResourceRows} from './benchmark-report.ts';
import {PUBLIC_POLICY_LABELS} from './benchmark-quality.ts';
export const classNames=['Unknown','Car','Bicycle','Motorcycle','Truck','Other vehicle','Person','Bicyclist','Motorcyclist','Road','Parking','Sidewalk','Other ground','Building','Fence','Vegetation','Trunk','Terrain','Pole','Traffic sign'];
export const datasetFormats=[['generic','Generic manifest'],['semanticposs','SemanticPOSS'],['semantickitti','SemanticKITTI'],['rellis3d','RELLIS-3D']] as const;
export interface DashboardEvent {time:number;message:string;kind:string}
export function defaultSessionConfig():Json{return defaultRuntimeConfig();}
export function evidenceAvailable(value:unknown){return typeof value==='string'&&value.length>0&&!['unavailable','disabled','skipped','invalid'].includes(value);}
export function profileConfig(current:Json,name:string):Json{
 if(name==='LowResource'){const low=defaultRuntimeConfig();return {...current,preset:name,map:{...current.map,...low.map,policy:current.map?.policy??low.map.policy},playback:{...current.playback,...low.playback},visualization:low.visualization};}
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
// Ground-truth styling keys on the ACTUAL provider (telemetry provider is
// derived from actual): Ground Truth iff actual normalizes to ground_truth.
// A requested-neural / actual-GT mismatch is a debug/eval fallback, never
// neural ACTIVE styling. Extra requested/actual/fallback keys are optional so
// legacy callers (and their tests) keep their existing strings; new telemetry
// passes {requested, actual, fallbackReason} to unlock fallback/neural labels.
export function semanticDisplay(provider:unknown,model:unknown,execution:unknown,backend:unknown,extra?:{requested?:unknown;actual?:unknown;fallbackReason?:unknown}):{source:string;sourceSub:string;neural:string;neuralSub:string;execution:string;executionSub:string;isFallback:boolean;isExplicitGT:boolean;isNeural:boolean;banner:string|null;bannerSub:string|null;debugChip:string|null}{
 const text=(value:unknown)=>typeof value==='string'&&value&&value!=='unavailable'?String(value).replaceAll('_',' '):'Unavailable';
 const norm=(value:unknown)=>typeof value==='string'&&value?value.toLowerCase().replaceAll(' ','_').replaceAll('-','_'):'';
 const shortModel=(value:unknown)=>{if(typeof value!=='string'||!value||value==='unavailable')return 'Unavailable';const base=String(value).split(/[/\\]/).pop()??String(value);return base||'Unavailable';};
 const prettyProvider=(value:unknown)=>{const n=norm(value);if(n==='cenet')return 'CENet';if(n==='salsanext')return 'SalsaNext';return text(value);};
 const fallbackReason=typeof extra?.fallbackReason==='string'&&extra.fallbackReason?extra.fallbackReason:null;
 const requestedRaw=extra?.requested??null;
 const requestedNorm=norm(requestedRaw);
 // Actual wins when supplied; otherwise the legacy provider field already
 // carries the actual-derived display value ("Ground Truth" or neural name).
 const actualRaw=extra?.actual??null;
 const actualNorm=actualRaw!=null&&actualRaw!==''?norm(actualRaw):norm(provider)==='ground truth'?'ground_truth':norm(provider)||norm(backend);
 const isGT=actualNorm==='ground_truth';
 const isFallback=isGT&&!!requestedNorm&&requestedNorm!=='ground_truth'&&requestedNorm!=='unavailable';
 const isExplicitGT=isGT&&!isFallback;
 const base={isFallback,isExplicitGT,isNeural:!isGT,banner:null as string|null,bannerSub:null as string|null,debugChip:null as string|null};
 if(isFallback){
  const requestedLabel=typeof requestedRaw==='string'&&requestedRaw?requestedRaw:'unknown';
  const parts:string[]=[];
  if(fallbackReason)parts.push(fallbackReason);
  parts.push(`requested ${text(requestedLabel)} / actual ground truth`);
  parts.push(`model ${model?shortModel(model):'unavailable'}`);
  parts.push(`exec ${typeof execution==='string'&&execution&&execution!=='unavailable'?text(execution):'bypassed'}`);
  const sub=parts.join(' · ');
  const banner='NEURAL UNAVAILABLE — SHOWING DEBUG/EVAL GROUND TRUTH';
  return {...base,source:banner,sourceSub:sub,neural:'UNAVAILABLE',neuralSub:'model unavailable',execution:'BYPASSED',executionSub:'no accelerator involved',banner,bannerSub:sub,debugChip:'DEBUG/EVAL'};
 }
 if(isExplicitGT)return {...base,source:'DATASET GROUND TRUTH',sourceSub:'dataset labels used directly',neural:'BYPASSED',neuralSub:'model latency not measured',execution:'N/A',executionSub:'no accelerator involved',debugChip:'DEBUG/EVAL'};
 // Pure neural success: backend-verified device plus model short path. Only
 // the new telemetry path (extra.actual supplied) uses the NEURAL label so
 // legacy callers keep their existing source string.
 if(extra&&actualRaw!=null&&actualRaw!==''){
  const execName=typeof execution==='string'&&execution&&execution!=='unavailable'?execution.toUpperCase()==='CPU'?'CPU':text(execution):'Unavailable';
  const source=`NEURAL ${prettyProvider(provider)} · ${execName} (backend-verified)`;
  return {...base,source,sourceSub:`neural inference · ${text(backend)}`,neural:model?'ACTIVE':'UNAVAILABLE',neuralSub:shortModel(model),execution:text(execution),executionSub:'backend-verified device only'};
 }
 if(provider==='Ground Truth')return {...base,source:'DATASET GROUND TRUTH',sourceSub:'dataset labels used directly',neural:'BYPASSED',neuralSub:'model latency not measured',execution:'N/A',executionSub:'no accelerator involved',debugChip:'DEBUG/EVAL'};
 return {...base,source:text(provider),sourceSub:`neural inference · ${text(backend)}`,neural:model?'ACTIVE':'UNAVAILABLE',neuralSub:text(model),execution:text(execution),executionSub:'backend-verified device only'};
}
// Historical-data marker: stale telemetry values are last measured, never live.
export function lastMeasuredPrefix(isStale:boolean):string{return isStale?'LAST MEASURED · ':'';}
// Canonical benchmark capture states. Warmup exclusion is reported post-hoc
// from the artifact (no live warmup signal exists); never claim COMPLETE
// merely because the runtime paused.
export function measurementDisplay(state:unknown):{label:string;sub:string}{
 if(state==='running')return {label:'MEASURING',sub:'frames processing; warmup excluded per artifact'};
 if(state==='loading')return {label:'LOADING REPORT',sub:'benchmark finished; reading the complete artifact'};
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
// Compact four-policy summary for the Overview. Same canonical rows as the
// Evaluation comparison: logical map bytes (not process RSS) and the map-update
// percentile that is reliable for every policy (p95 at >=20 samples, else p50).
export function comparisonMetrics(report:Json|null){
 const rows=qualityResourceRows(report),scope=comparisonScope(report);
 const uniform=rows.find(row=>row.policy==='uniform5')?.logicalBytes??null;
 const entries=rows.map(row=>({policy:row.policy,label:PUBLIC_POLICY_LABELS[row.policy],memory:row.logicalBytes,latency:scope.latencyMetric==='p95'?row.mapP95Ms:row.mapP50Ms,memoryReduction:uniform!==null&&uniform>0&&row.logicalBytes!==null&&row.policy!=='uniform5'?(1-row.logicalBytes/uniform)*100:null}));
 const max=(values:(number|null)[])=>Math.max(0,...values.filter((value):value is number=>value!==null));
 return {rows:entries,latencyMetric:scope.latencyMetric,memoryMax:max(entries.map(entry=>entry.memory)),latencyMax:max(entries.map(entry=>entry.latency)),sameInput:scope.sameInput};
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
// ---- Judge-demo proof helpers (display only; never fabricate evidence) ----
export const GLOSSARY:Record<string,string>={
 '2.5D':'One adaptive XY grid cell storing height + scene statistics — not a dense XYZ voxel volume.',
 'LOD':'Level of detail: L0 5 cm near the robot, L3 40 cm far away. Utility evidence can promote important cells finer.',
 'RSS':'Resident set size: OS-measured process memory. Different from map logical/allocated bytes.',
 'RMSE':'Root-mean-square elevation error vs the executed Uniform 5 cm reference on the same frames.',
 'p95':'95th percentile latency: 95% of frames were faster. Nearest-rank; needs ≥20 samples to be meaningful.',
 'UtilityLOD':'Distance baseline plus promotion on geometry, semantics, motion and traversability risk — quality-gated. Currently inconclusive vs DistanceLOD on the tested selection.',
 'DistanceLOD':'Range-only baseline: 0–10 m → 5 cm, 10–30 m → 10 cm, 30–60 m → 20 cm, 60–100 m → 40 cm.',
 'Governor':'Resource guard: blocks optional splits near budget, merges low-value distant cells first, never coarsens the 10 m safety disk.',
};
export function fmtCell(value:unknown,decimals=3):string{
 if(typeof value!=='number'||!Number.isFinite(value))return 'Unavailable';
 return value.toLocaleString(undefined,{maximumFractionDigits:decimals});
}
export function lodLabel(level:unknown,resolution:unknown):string{
 if(typeof level==='number'&&Number.isFinite(level))return `L${level}`;
 if(typeof resolution==='number'&&Number.isFinite(resolution)&&resolution>0){
  const level=Math.round(Math.log2(resolution/0.05));
  if(level>=0&&level<=3)return `L${level}`;
 }
 return 'Unavailable';
}
export function resolutionLabel(resolution:unknown):string{
 if(typeof resolution!=='number'||!Number.isFinite(resolution)||resolution<=0)return 'Unavailable';
 const cm=resolution*100;
 return `${Number.isInteger(cm)?cm:cm.toFixed(1)} cm`;
}
export function semanticName(id:unknown):string{
 if(typeof id!=='number'||!Number.isFinite(id))return 'Unavailable';
 return classNames[id]??`Class ${id}`;
}
export function traversabilityLabel(evidence:unknown):string{
 if(typeof evidence!=='number'||!Number.isFinite(evidence))return 'Unavailable';
 if(evidence>0)return 'Drivable';
 if(evidence<0)return 'Non-drivable';
 return 'Unknown';
}
export function motionLabel(probability:unknown):string{
 if(typeof probability!=='number'||!Number.isFinite(probability))return 'Unavailable';
 if(probability>=0.5)return 'MOVING';
 if(probability>0)return 'POSSIBLY MOVING';
 return 'STATIC';
}
export interface InspectorRow{key:string;label:string;value:string;hint:string}
export function inspectorRows(cell:Json):InspectorRow[]{
 const f=(v:unknown,d=3)=>fmtCell(v,d);
 return [
  {key:'xy',label:'XY (m)',value:typeof cell.x==='number'&&typeof cell.y==='number'&&Number.isFinite(cell.x)&&Number.isFinite(cell.y)?`${f(cell.x)} , ${f(cell.y)}`:'Unavailable',hint:'World-aligned cell center in odom'},
  {key:'resolution',label:'Resolution',value:resolutionLabel(cell.resolution),hint:'Cell edge length'},
  {key:'lod',label:'LOD level',value:lodLabel(cell.lod_level,cell.resolution),hint:'L0 5 cm · L1 10 cm · L2 20 cm · L3 40 cm'},
  {key:'z',label:'Pooled height mean (m)',value:f(cell.elevation),hint:'Average of all layers; not necessarily an observed surface'},
  {key:'zmin',label:'Height min (m)',value:f(cell.height_min),hint:'Lowest observed height'},
  {key:'zmax',label:'Height max (m)',value:f(cell.height_max),hint:'Highest observed height'},
  {key:'zvar',label:'Height variance',value:f(cell.height_variance,5),hint:'Surface roughness signal'},
  {key:'count',label:'Point count',value:f(cell.point_count,0),hint:'Returns fused into this cell'},
  {key:'class',label:'Semantic class',value:semanticName(cell.semantic_class),hint:'Mapped taxonomy ID'},
  {key:'semconf',label:'Semantic confidence',value:f(cell.semantic_confidence),hint:'0–1, unknown class is 0'},
  {key:'ground',label:'Ground evidence',value:f(cell.ground_evidence),hint:'Positive = ground support'},
  {key:'trav',label:'Traversability',value:traversabilityLabel(cell.drivable_evidence),hint:'Unknown is never drivable'},
  {key:'motion',label:'Motion',value:motionLabel(cell.motion),hint:'From temporal tracking'},
  {key:'quality',label:'Observation quality',value:f(cell.quality),hint:'Gates UtilityLOD promotion'},
  {key:'utility',label:'Utility score',value:f(cell.utility),hint:'Promotion signal 0–1'},
  ...(['ground','obstacle','overhead'] as const).flatMap(name=>{
   const layer=cell.physical_layers?.[name];
   const title=name[0].toUpperCase()+name.slice(1);
   const supported=typeof layer?.count==='number'&&layer.count>0;
   return [
    {key:`${name}_count`,label:`${title} returns`,value:f(layer?.count,0),hint:'Zero means no observed surface in this layer'},
    {key:`${name}_mean`,label:`${title} height (m)`,value:f(supported?layer.mean:null),hint:'Measured layer mean, not pooled elevation'},
    {key:`${name}_extent`,label:`${title} min / max (m)`,value:supported?`${f(layer.min)} / ${f(layer.max)}`:'Unavailable',hint:'Observed vertical extent in world coordinates'},
   ];
  }),
 ];
}
export function datasetCapabilities(catalog:Json|null,sequenceId:string){
 const seq=(catalog?.sequences??[]).find((s:Json)=>s.id===sequenceId)??{};
 const labels=typeof seq.labels==='number'?seq.labels:seq.paired;
 return {
  frames:seq.frames??null,labels:typeof labels==='number'?labels:null,
  poses:seq.poses??null,timestamps:seq.timestamps??null,
  semantic:typeof labels==='number'&&labels>0?'available':'unavailable',
  motion:seq.timestamps===true||(typeof seq.timestamps==='number'&&seq.timestamps>0)?'available':'unavailable — no dataset timestamps',
 };
}
export function sessionPhase(catalog:Json|null,status:Json,awaiting:boolean):string{
 if(awaiting||status.state==='unconfigured'&&catalog==null)return awaiting?'VALIDATING':'EMPTY';
 if(catalog!=null&&!status.frames)return 'LOADED';
 if(status.frames>0)return 'READY';
 return 'EMPTY';
}
