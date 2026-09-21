<script lang="ts">
 import type {Json} from '../core';
 let {report=null}=$props<{report?:Json|null}>();
 const labels:Record<string,string>={uniform5:'Uniform5',uniform40:'Uniform40',distance_lod:'DistanceLOD',utility_lod:'UtilityLOD'};
 const number=(value:unknown,decimals=2)=>typeof value==='number'&&Number.isFinite(value)?value.toLocaleString(undefined,{maximumFractionDigits:decimals}):'—';
 const bytes=(value:unknown)=>typeof value==='number'&&Number.isFinite(value)?`${(value/1048576).toLocaleString(undefined,{maximumFractionDigits:1})} MB`:'—';
 function rows(){
  const policies=(report?.mapping??report)?.policies??{};
  const result=Object.entries(policies).map(([key,value])=>({key,label:labels[key]??key,status:'MEASURED',value:value as Json}));
  const baselines=(report?.baselines??report?.comparison??{}) as Json;
  for(const key of ['measured_3d','measured_3d_baseline','analytical_3d','analytical_dense_reference']){
   const value=baselines[key];
   if(value&&typeof value==='object')result.push({key,label:key.includes('analytical')?'Dense 3D reference':'Measured 3D baseline',status:key.includes('analytical')?'ANALYTICAL':'MEASURED',value:value as Json});
  }
  if(!result.some(row=>row.key.includes('3d')))result.push({key:'3d-unavailable',label:'Measured 3D baseline',status:'UNAVAILABLE',value:{}});
  return result;
 }
 function aggregate(value:Json){return (value.aggregate??value.metrics??value) as Json;}
 function mapLatency(value:Json,key:string){const latency=aggregate(value).stage_latency_ns as Json|undefined;return typeof latency?.map_update==='object'?number((latency.map_update as Json)[key]!=null?Number((latency.map_update as Json)[key])/1e6:null):'—';}
 function logicalBytes(value:Json){const direct=value.logical_map_bytes;const memory=value.memory as Json|undefined;return bytes(typeof direct==='number'?direct:memory?.logical_map_bytes);}
 function rmse(value:Json){const quality=value.quality as Json|undefined;const elevation=quality?.elevation_vs_fine_reference as Json|undefined;return `${number(elevation?.rmse_m,4)} m`;}
</script>

<section class="card comparison-evidence" aria-label="Policy comparison evidence">
 <h3>Comparison evidence <span>MEASURED · ANALYTICAL · UNAVAILABLE</span></h3>
 <p class="hint">Every value is labeled by evidence source. Missing quality or memory measurements remain unavailable.</p>
 <div class="table-wrap"><table><thead><tr><th>Policy / baseline</th><th>Status</th><th>FPS p50</th><th>Map p50</th><th>Map p95</th><th>Map p99</th><th>Peak RSS</th><th>Logical bytes</th><th>Active leaves</th><th>Elevation RMSE</th></tr></thead><tbody>
  {#each rows() as row}
   {@const value=aggregate(row.value)}
   <tr><td>{row.label}</td><td><span class="chip">{row.status}</span></td><td>{number((value.fps as Json)?.p50)}</td><td>{mapLatency(row.value,'p50')} ms</td><td>{mapLatency(row.value,'p95')} ms</td><td>{mapLatency(row.value,'p99')} ms</td><td>{bytes(value.peak_rss_bytes)}</td><td>{logicalBytes(value)}</td><td>{number(Object.values((value.final_leaves_per_level??{}) as Json).reduce((sum:number,item)=>sum+(typeof item==='number'?item:0),0),0)}</td><td>{rmse(value)}</td></tr>
  {/each}
 </tbody></table></div>
</section>
