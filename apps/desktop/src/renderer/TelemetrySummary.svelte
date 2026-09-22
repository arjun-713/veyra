<script lang="ts">
 import type {Json} from '../core';
 import {telemetryFreshness} from './session';
 import {semanticDisplay} from './dashboard';
 let {telemetry={},renderer={},now=Date.now()}=$props<{telemetry?:Json;renderer?:Json;now?:number}>();
 const display=(value:unknown, suffix='')=>typeof value==='number'&&Number.isFinite(value)?`${value.toLocaleString(undefined,{maximumFractionDigits:2})}${suffix}`:'—';
 const state=(value:unknown)=>typeof value==='string'&&value&&value!=='unavailable'?String(value).replaceAll('_',' '):'Unavailable';
 const count=(values:unknown,key:string)=>typeof values==='object'&&values!==null&&typeof (values as Json)[key]==='number'?String((values as Json)[key]):'—';
 const semanticClass=(values:unknown,key:string)=>count(values,key);
 const perception=()=>telemetry.perception??{};
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
  <div class="stage-item"><span>Tracks</span><strong>{perception().track_counts==null?'Unavailable':'available'}</strong><small>no track data reported</small></div>
 </div>
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
