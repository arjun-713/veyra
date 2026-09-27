<script lang="ts">
 import type {Json} from '../core';
 import {telemetryFreshness} from './session';
 import {semanticDisplay} from './dashboard';
 let {telemetry={},renderer={},now=Date.now()}=$props<{telemetry?:Json;renderer?:Json;now?:number}>();
 const display=(value:unknown, suffix='')=>typeof value==='number'&&Number.isFinite(value)?`${value.toLocaleString(undefined,{maximumFractionDigits:2})}${suffix}`:'—';
 const state=(value:unknown)=>typeof value==='string'&&value&&value!=='unavailable'?String(value).replaceAll('_',' '):'Unavailable';
 const count=(values:unknown,key:string)=>typeof values==='object'&&values!==null&&typeof (values as Json)[key]==='number'?String((values as Json)[key]):'—';
 const semanticClass=(values:unknown,key:string)=>count(values,key);
 const trackLabel=(t:unknown)=>{if(t==null)return 'Unavailable';const n=typeof t==='number'?t:(typeof t==='object'?Object.keys(t as Json).length:NaN);if(typeof n!=='number'||!Number.isFinite(n))return '—';return n===0?'0 tracks':n===1?'1 track':`${n} tracks`;};
 const perception=()=>telemetry.perception??{};
 const totalRss=(value:Json)=>{const procs=value.processes??[];if(!procs.length||procs.some((p:Json)=>typeof p.rss_bytes!=='number'||!Number.isFinite(p.rss_bytes)))return null;return procs.reduce((s:number,p:Json)=>s+p.rss_bytes,0)/1048576;};
 const health=()=>telemetry.health??{};
 const stages=()=>telemetry.perception_stages_ms??{};
 let sem=$derived(semanticDisplay(perception().provider,perception().model,perception().execution_provider,perception().backend));
</script>

<section class="card perception-status" aria-label="Perception and runtime telemetry">
 <h3>Perception evidence <span>{state(perception().backend)}</span></h3>
 <div class="stage-grid">
  <div class="stage-item"><span>Semantic source</span><strong>{sem.source}</strong><small>{sem.sourceSub}</small></div>
  <div class="stage-item"><span>Neural inference</span><strong>{sem.neural}</strong><small>{sem.neuralSub}</small></div>
  <div class="stage-item"><span>Execution</span><strong>{sem.execution}</strong><small>{sem.executionSub}</small></div>
  <div class="stage-item"><span>Ground ratio</span><strong>{display(perception().ground_ratio!=null?perception().ground_ratio*100:null,'%')}</strong><small>{display(stages().ground,' ms')}</small></div>
  <div class="stage-item"><span>Semantic confidence</span><strong>{display(perception().semantic_confidence_mean)}</strong><small>{display(stages().semantic,' ms')}</small></div>
  <div class="stage-item"><span>Unknown ratio</span><strong>{display(perception().unknown_ratio!=null?perception().unknown_ratio*100:null,'%')}</strong><small>{display(perception().points, ' points')}</small></div>
  <div class="stage-item"><span>Drivable / non / unknown</span><strong>{count(perception().drivable_counts,'drivable')} / {count(perception().drivable_counts,'non_drivable')} / {count(perception().drivable_counts,'unknown')}</strong><small>point evidence</small></div>
  <div class="stage-item"><span>Vehicles / people</span><strong>{semanticClass(perception().semantic_class_counts,'1')} / {semanticClass(perception().semantic_class_counts,'6')}</strong><small>taxonomy IDs</small></div>
  <div class="stage-item"><span>Tracks</span><strong>{trackLabel(perception().track_counts)}</strong><small>{perception().track_counts==null?'no track data reported':'per-track point counts'}</small></div>
 </div>
</section>

<section class="card memory-domains" aria-label="Memory domains">
 <h3>Memory by domain <span>MEASURED · NOT COMPARABLE</span></h3>
 <div class="data-row"><span title="Live C++ snapshot payload bytes">Logical map memory</span><b>{display(telemetry.map?.logical_bytes?telemetry.map.logical_bytes/1048576:null,' MB')}</b></div>
 <div class="data-row"><span title="Live C++ allocated bytes (tile tables + index + overhead)">Allocated map memory</span><b>{display(telemetry.map?.allocated_bytes?telemetry.map.allocated_bytes/1048576:null,' MB')}</b></div>
 <div class="data-row"><span title="OS-measured RSS of the C++ mapper process">Mapper RSS</span><b>{display((telemetry.processes??[]).find((p:Json)=>p.name==='mapper')?.rss_bytes!=null?(telemetry.processes??[]).find((p:Json)=>p.name==='mapper').rss_bytes/1048576:null,' MB')}</b></div>
 <div class="data-row"><span title="OS-measured RSS of the Python runtime process">Python runtime RSS</span><b>{display((telemetry.processes??[]).find((p:Json)=>p.name==='runtime')?.rss_bytes!=null?(telemetry.processes??[]).find((p:Json)=>p.name==='runtime').rss_bytes/1048576:null,' MB')}</b></div>
 <div class="data-row"><span title="Sum of measured backend processes; excludes the desktop shell">Total backend RSS</span><b>{display(totalRss(telemetry),' MB')}</b></div>
 <p class="hint">Logical vs allocated vs process RSS measure different domains — do not compare across rows. No system-wide RAM is shown as Veyra RAM.</p>
</section>

<section class="card health-status" aria-label="Runtime health">
 <h3>Runtime health <span>{state(health().runtime)}</span></h3>
 <div class="data-row"><span>Runtime</span><b>{state(health().runtime)}</b></div>
 <div class="data-row"><span>Perception</span><b>{state(health().perception)}</b></div>
 <div class="data-row"><span>Mapper</span><b>{state(health().mapper)}</b></div>
 <div class="data-row"><span>Renderer / WebGL</span><b>{state(renderer.status)}</b></div>
 <div class="data-row"><span>Telemetry freshness</span><b>{telemetryFreshness(telemetry,now)}</b></div>
 <p class="hint">Counts are point evidence unless a track count is explicitly supplied by the runtime. Missing values remain unavailable.</p>
</section>
