<script lang="ts">
 import MapCanvas from './MapCanvas.svelte';import Icon from './Icon.svelte';
 import {comparisonMetrics,gateStatistic,MEMORY_DOMAIN_NOTE,MOTION_FEATURE_ENABLED,MIN_SAMPLES,processingDisplay,summarizeVisual,type DashboardEvent} from './dashboard';
 import {processRss} from './session';
 import {POLICY_COLORS} from './benchmark-quality';
 import {sessionActive} from './setup';
 import type {Json,WireFrame} from '../core';
 let {status,telemetry,frame,report,events,openDataset,openPerformance,openMap,openBenchmarks,busy=false,awaitingFrame=false}=$props<{status:Json;telemetry:Json;frame:WireFrame|null;report:Json|null;events:DashboardEvent[];openDataset:()=>void;openPerformance:()=>void;openMap:()=>void;openBenchmarks:()=>void;busy?:boolean;awaitingFrame?:boolean}>();
 let rawView=$state('orbit'),semanticView=$state('orbit'),mapView=$state('top'),eventFilter=$state('all');
 const f=(n:any,d=1)=>typeof n==='number'&&Number.isFinite(n)?n.toLocaleString(undefined,{maximumFractionDigits:d}):'—';
 const memory=(n:any)=>typeof n==='number'?n>=1073741824?f(n/1073741824,2)+' GB':f(n/1048576,1)+' MB':'—';
 let comparison=$derived(comparisonMetrics(report)),summary=$derived(summarizeVisual(frame));
 let rss=$derived(processRss(telemetry.processes??[]));
 let storyLayers=$derived(frame?.metadata.layers??{});
 const storyDot=(v:string)=>v==='available'||v==='model'||v==='ground_truth'?'ok':v==='unavailable'||v==='disabled'||!v?'off':'warn';
 let storySteps=$derived([['Raw LiDAR',frame?'live':'empty',frame?(typeof frame.metadata.n_points==='number'?`${frame.metadata.n_points.toLocaleString()} pts`:'frame live'):status.frames?'waiting':'no dataset'],['Perception',storyDot(storyLayers.semantic),storyLayers.semantic??'—'],['Terrain',storyDot(storyLayers.terrain),storyLayers.terrain??'—'],...(MOTION_FEATURE_ENABLED?[['Motion',storyDot(storyLayers.motion),storyLayers.motion??'—']]:[]),['Adaptive 2.5D',(frame?.metadata.cells?.count??0)>0?'live':'empty',telemetry.map?.active_cells!=null?`${telemetry.map.active_cells.toLocaleString()} cells`:'—'],['Evidence',report?'ready':'none',report?'benchmark loaded':'run or open a report']]);

 let proc=$derived(processingDisplay(status,telemetry));
 let e2eCount=$derived(telemetry.latency_ms?.end_to_end?.count);
 let e2eP95=$derived(gateStatistic(telemetry.latency_ms?.end_to_end?.p95,e2eCount,MIN_SAMPLES.p95));
 let cards=$derived([{icon:'speed',label:'Processing',value:proc.label,unit:'',detail:proc.sub},{icon:'bolt',label:'Rolling E2E p95',value:e2eP95.text,unit:e2eP95.ok?'ms':'',detail:`Backend rolling percentile · ${e2eP95.sub}`},{icon:'chip',label:'Backend RSS',value:typeof rss==='number'?f(rss/1048576,0):'—',unit:'MB',detail:'Python runtime + mapper · excludes desktop shell'},{icon:'grid',label:'Active Cells',value:f(telemetry.map?.active_cells,0),unit:'',detail:'Live map leaves'}]);
 function width(value:any,reference:any){return typeof value==='number'&&typeof reference==='number'&&reference>0?Math.max(1,Math.min(100,value/reference*100)):0;}
</script>
<div class="dashboard">
 {#if !frame&&!sessionActive(status)&&!awaitingFrame}
  <section class="welcome" aria-labelledby="welcome-title">
   <div class="welcome-mark"><Icon name="map" size={40}/></div>
   <h2 id="welcome-title">Your environment, mapped.</h2>
   <p>Open a LiDAR dataset to explore its observations, semantic evidence and adaptive 2.5D map.</p>
   <button class="primary" disabled={busy} onclick={openDataset}><Icon name="folder" size={19}/>Set up a session</button>
   <ol class="welcome-flow">
    <li><Icon name="database" size={21}/><div><strong>Choose a source</strong><span>Select a dataset folder and sequence. Your files stay local.</span></div></li>
    <li><Icon name="play" size={21}/><div><strong>Preview and replay</strong><span>Open the first frame, then play and inspect layers in Viewer.</span></div></li>
    <li><Icon name="chart" size={21}/><div><strong>Measure the trade-off</strong><span>Compare map quality with latency and memory in Evaluation.</span></div></li>
   </ol>
  </section>
 {:else}
  <div class="overview-session"><div><h2>{awaitingFrame?'Preparing your preview':status.dataset??'Current session'}</h2><p>Sequence {status.sequence??'—'} · {f(status.frames,0)} frames · {status.policy?.replaceAll('_',' ')??'No policy'}</p></div><button class="primary" disabled={busy} onclick={openMap}><Icon name="map" size={18}/>Open Viewer</button></div>
 <div class="demo-story" aria-label="Demo story">
  {#each storySteps as [label,state,detail]}
   <span class="story-step"><i class={state}></i><b>{label}</b><small>{detail}</small></span>{#if label!=='Evidence'}<span class="story-arrow"><Icon name="chevron" size={14}/></span>{/if}
  {/each}
 </div>
 <div class="dashboard-metrics">{#each cards as card}<button class="dashboard-metric" onclick={card.icon==='database'||card.icon==='chart'?openBenchmarks:openPerformance}><span class="metric-symbol"><Icon name={card.icon} size={25}/></span><div><h2>{card.label}</h2><div class="metric-number">{card.value}<small>{card.unit}</small></div><p>{card.detail}</p></div></button>{/each}</div>
 <div class="dashboard-map-grid">
  {#each [{title:'Raw LiDAR Point Cloud',icon:'cube',mode:'raw',cells:false},{title:'Semantic LiDAR',icon:'semantic',mode:'semantic',cells:false},{title:'Adaptive 2.5D Map',icon:'map',mode:'lod',cells:true}] as panel,i}
   <section class="dashboard-panel visualization-panel"><div class="dashboard-panel-title"><Icon name={panel.icon}/><h2>{panel.title}</h2><select aria-label={`${panel.title} camera`} value={i===0?rawView:i===1?semanticView:mapView} onchange={e=>{if(i===0)rawView=e.currentTarget.value;else if(i===1)semanticView=e.currentTarget.value;else mapView=e.currentTarget.value;}}><option value="orbit">3D View</option><option value="top">Top-Down</option><option value="driver">Driver</option></select></div>
    <div class="dashboard-map"><MapCanvas {frame} mode={panel.mode} showPoints={!panel.cells} showCells={panel.cells} accumulate={panel.cells?1:20} boundaries={false} view={i===0?rawView:i===1?semanticView:mapView} follow={true}/>{#if !frame}<div class="dashboard-map-empty"><Icon name={panel.icon} size={34}/><strong>{awaitingFrame?'Processing first frame…':status.frames?'Waiting for visualization':'No dataset preview'}</strong><span>{status.frames?'Open Viewer to inspect session status.':'Choose a directory and open a preview.'}</span><button disabled={busy} onclick={status.frames?openMap:openDataset}>{status.frames?'Open Viewer':'Choose dataset'}</button></div>{/if}{#if panel.cells}<div class="map-mini-legend">{#each [['#33d9f2','5 cm'],['#4dd980','10 cm'],['#ffb340','20 cm'],['#d966d9','40 cm']] as [color,label]}<span><i style:background={color}></i>{label}</span>{/each}</div>{/if}<div class="axis-marker"><span>Z</span><b>Z</b><small>Y / X</small></div></div>
    {#if i===1}<div class="semantic-legend"><span><i style:background=" #388cfa"></i>Road</span><span><i style:background=" #f14d62"></i>Vehicle</span><span><i style:background=" #a457ec"></i>Person</span><span><i style:background=" #38b34c"></i>Terrain</span></div>{/if}
    <div class="visualization-caption">{#if panel.cells}<span>Cells shown: <b>{f(frame?.metadata.cells?.count,0)}</b> / {f(frame?.metadata.total_leaves,0)}</span><span>{status.policy?.replaceAll('_',' ')??'No policy'}</span>{:else}<span>Points shown: <b>{f(frame?.metadata.points?.count,0)}</b> / {f(frame?.metadata.n_points,0)}</span><span>{i===0?'World coordinates':`Semantic classes: ${summary.length||'—'}`}</span>{/if}</div>
   </section>
  {/each}
  <section class="dashboard-panel policy-panel"><div class="dashboard-panel-title"><Icon name="settings"/><h2>Resolution Policy</h2></div><table><thead><tr><th>Range</th><th>Cell Size</th><th>Logic</th></tr></thead><tbody>{#each [['Near Field','0–10 m','5 cm','Protected safety detail'],['Mid Field','10–30 m','10 cm','Balanced detail and efficiency'],['Outer Field','30–60 m','20 cm','Coarser mapping for large structures'],['Far Field','60–100 m','40 cm','Bounded distant terrain']] as row}<tr><td><strong>{row[0]}</strong><span>({row[1]})</span></td><td><strong>{row[2]}</strong></td><td>{row[3]}</td></tr>{/each}</tbody></table><div class="policy-utility"><p>These are the DistanceLOD base bands. UtilityLOD may promote cells when evidence permits.</p><button onclick={openMap}><Icon name="settings" size={16}/>Change policy in Viewer</button></div></section>
 </div>
 <div class="dashboard-bottom-grid">
  <section class="dashboard-panel comparison-panel"><div class="dashboard-panel-title"><Icon name="chart"/><h2>Resource comparison</h2></div>{#if report}{#each [{label:'Logical map memory ↓',key:'memory',max:comparison.memoryMax},{label:`Map update ${comparison.latencyMetric} ↓`,key:'latency',max:comparison.latencyMax}] as metric}<div class="comparison-row"><strong>{metric.label}</strong><div class="comparison-bars">{#each comparison.rows as row}{@const value=metric.key==='memory'?row.memory:row.latency}<div title={row.label}><i style:background={POLICY_COLORS[row.policy]} style:width={`${width(value,metric.max)}%`}></i><span>{row.label} · {value===null?'unavailable':metric.key==='memory'?memory(value):f(value,2)+' ms'}{metric.key==='memory'&&row.memoryReduction!==null?` (${f(row.memoryReduction,0)}% less than Uniform5)`:''}</span></div>{/each}</div></div>{/each}<p class="dashboard-footnote">Same benchmark report as Evaluation{comparison.sameInput===true?', identical input for all four policies':comparison.sameInput===false?' — policies did NOT consume identical input':''}. Separate from the live session. {MEMORY_DOMAIN_NOTE} <button class="link-button" onclick={openBenchmarks}>Open full comparison</button></p>{:else}<p class="dashboard-footnote">Open or run a report in Evaluation to compare quality and resource cost across Uniform5, Uniform40, DistanceLOD and UtilityLOD.</p>{/if}</section>
  <section class="dashboard-panel summary-panel"><div class="dashboard-panel-title"><Icon name="pie"/><h2>Object & Terrain Summary</h2></div><table><thead><tr><th>Semantic class</th><th>Points</th><th>Percentage</th></tr></thead><tbody>{#each summary.slice(0,6) as item}<tr><td><i class="summary-dot" style:background={['#99a9bb','#f14d62','#f6ac23','#f6ac23','#f14d62','#f14d62','#a457ec','#a457ec','#a457ec','#388cfa','#7188cf','#8fa9d4','#b8966f','#7b8a9e','#a2a0b6','#38b34c','#7b9950','#61ae57','#f6ac23','#e5b757'][item.id]??'#99a9bb'}></i>{item.name}</td><td>{f(item.count,0)}</td><td>{f(item.percent)}%</td></tr>{:else}{#each ['Road / drivable surface','Vehicles','People','Vegetation / terrain'] as name}<tr><td><i class="summary-dot"></i>{name}</td><td>—</td><td>—</td></tr>{/each}{/each}</tbody></table><p class="dashboard-footnote">{summary.length?'Displayed semantic points; counts are not tracked objects.':'Semantic observations unavailable.'}</p></section>
  <section class="dashboard-panel event-panel"><div class="dashboard-panel-title"><Icon name="file"/><h2>Event Log</h2><select aria-label="Event filter" bind:value={eventFilter}><option value="all">All Events</option><option value="error">Errors</option><option value="benchmark">Benchmarks</option></select></div><div class="event-list">{#each events.filter((e:DashboardEvent)=>eventFilter==='all'||e.kind===eventFilter).slice(-30).reverse() as event}<div class="event-item"><i class:error={event.kind==='error'}></i><time>{new Date(event.time).toLocaleTimeString(undefined,{hour12:false})}</time><p>{event.message}</p></div>{:else}<div class="events-empty">No runtime events yet.<span>Session changes and backend diagnostics appear here.</span></div>{/each}</div><p class="dashboard-footnote">Latest 200 events retained.</p></section>
 </div>
 {/if}
</div>
