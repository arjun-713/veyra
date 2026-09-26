<script lang="ts">
 import {onMount} from 'svelte';
 import MapCanvas from './MapCanvas.svelte';import Chart from './Chart.svelte';import Dashboard from './Dashboard.svelte';import TelemetrySummary from './TelemetrySummary.svelte';import ComparisonEvidence from './ComparisonEvidence.svelte';import Icon from './Icon.svelte';import SessionSetup from './SessionSetup.svelte';import {errorRecovery,runtimeLabel,sessionActive} from './setup';import {defaultSessionConfig, FIRST_CPU_SAMPLE_NOTE, formatRenderAge, gateStatistic, inputTargetFps,measurementDisplay,isRenderStale,layerUnavailable,mapActivity,MEMORY_DOMAIN_NOTE,MIN_SAMPLES,perceptionStages,processingDisplay,lastMeasuredPrefix,profileConfig,recordEvent,telemetryConfiguredHz,GLOSSARY,inspectorRows,semanticName,traversabilityLabel,classNames,type DashboardEvent} from './dashboard';
 import {semanticRGB,cssRGB} from './colors';
 import veyraLogo from '../assets/veyra-logo.png';
 import {policies,type Json,type WireFrame} from '../core';import {nativeRuntimeUnavailableMessage} from '../api';
 import {acceptFrame,canPlayback,diagnosticMessage,formatTelemetryAge,processRss,telemetryFreshness,mergeSessionStatus,validationOutcome} from './session';
 let workspace=$state('Dashboard'),status=$state<Json>({state:'unconfigured',index:0,frames:0,policy:'distance_lod',speed:1}),telemetry=$state<Json>({}),desktop=$state<Json>({}),render=$state<Json>({}),info=$state<Json>({});
 let frame=$state.raw<WireFrame|null>(null),samples=$state<Json[]>([]),error=$state(''),notice=$state(''),busy=$state(false),catalog=$state<Json|null>(null),inspector=$state<Json|null>(null);
 let dataset=$state('generic'),sequence=$state(''),config=$state<Json>(defaultSessionConfig());
 let configText=$state(''),mode=$state('semantic'),showPoints=$state(true),showCells=$state(true),boundaries=$state(false),view=$state('orbit'),follow=$state(false),accumulate=$state(20),seekIndex=$state(0),preset=$state('LowResource'),viewMode=$state('both'),showRings=$state(false);
 function setViewMode(next:string){viewMode=next;showPoints=next!=='map';showCells=next!=='raw';}
 let report=$state<Json|null>(null),previousReport=$state<Json|null>(null),benchmarkState=$state('idle'),benchmarkCount=$state(100),validationState=$state('idle'),validationResult=$state<Json|null>(null);
 let events=$state<DashboardEvent[]>([]);
 let now=$state(Date.now()),awaitingFrame=$state(false);
 const playbackEnabled=()=>canPlayback(status,busy);
 const labels:Record<string,string>={uniform5:'Uniform 5 cm',uniform40:'Uniform 40 cm',distance_lod:'Distance LOD',utility_lod:'Utility LOD'};
 const proc=$derived(processingDisplay(status,telemetry));
 const liveStale=$derived(telemetryFreshness(telemetry,now)==='Stale');
 const staleAge=$derived(formatTelemetryAge(telemetry,now));
 const teleHz=$derived(telemetryConfiguredHz(config));
 const e2e=()=>telemetry.latency_ms?.end_to_end??{};
 const e2eStat=(key:string,min:number)=>gateStatistic(e2e()[key],e2e().count,min);
 const lastMeasured=()=>lastMeasuredPrefix(liveStale);
 const format=(value:any,decimals=1)=>typeof value==='number'&&Number.isFinite(value)?value.toLocaleString(undefined,{maximumFractionDigits:decimals}):'—';
 const mb=(value:any)=>typeof value==='number'?format(value/1048576)+' MB':'—';
 function rows(value:Json|null){const mapping=value?.mapping??value;return Object.entries(mapping?.policies??{}) as [string,Json][];}
 function quality(value:Json){return value.aggregate?.quality?.at(-1)?.elevation_vs_fine_reference?.rmse_m;}
 async function action(fn:()=>Promise<any>){if(busy)return;busy=true;error='';notice='';try{return await fn();}catch(e){error=e instanceof Error?e.message:String(e);awaitingFrame=false;}finally{busy=false;}}
 function clearSessionView(){frame=null;telemetry={};render={};samples=[];inspector=null;}
 async function command(name:string,args:Json={}){return action(async()=>{const reload=['sequence','reset','policy'].includes(name);if(reload){clearSessionView();awaitingFrame=true;}const r=await window.veyra.command(name,args);if(r.status)status=mergeSessionStatus(status,r.status);if(reload){const preview=await window.veyra.command('step');if(preview.status)status=preview.status;}return r;});}
let governorOverride=$state('automatic');
function syncGovernorOverride(value:unknown){if(value==='automatic'||value==='disabled'||value==='conserve')governorOverride=value;}
 async function setGovernor(mode:string){const previous=governorOverride;governorOverride=mode;const response=await command('governor',{mode});if(!response)governorOverride=previous;}
 async function setLayer(layer:string){const response=await command('layer',{layer});if(response){mode=layer;notice=`Layer changed to ${layer}.`;
  // Points have no LOD/utility colour and would bury the cells; reveal the map.
  if(layer==='lod'||layer==='utility')setViewMode('map');}}
 async function stopRuntime(){await action(async()=>{const response=await window.veyra.stop();if(response?.status)status=response.status;clearSessionView();awaitingFrame=false;notice='Runtime stopped. Open the dataset again to begin a new session.';});}
 async function runValidation(){await action(async()=>{validationState='running';validationResult=null;try{const response=await window.veyra.command('validation');if(response?.status)status=response.status;if(response?.result)validationResult=response.result;validationState=response?.result?.status==='pass'?'pass':'fail';}catch(error){validationState='fail';throw error;}});}
 async function runBenchmark(){await action(async()=>{benchmarkState='running';try{const response=await window.veyra.command('benchmark',{dataset:status.dataset,sequence:status.sequence,count:benchmarkCount});if(response.result?.report){report=response.result.report;benchmarkState='complete';}}catch(e){benchmarkState='failed';throw e;}});}
 async function restartRuntime(){await action(async()=>{clearSessionView();awaitingFrame=true;const response=await window.veyra.restart();if(response.status)status=response.status;if(status.frames){const preview=await window.veyra.command('step');if(preview.status)status=preview.status;}else{awaitingFrame=false;notice='Runtime restarted. Open a dataset preview to continue.';}});}
function confirmSaved(ok:unknown,saved:string,cancelled:string){notice=ok?saved:cancelled;}
 function refreshText(){configText=JSON.stringify(config,null,2);}
 async function chooseDataset(){await action(async()=>{const response=await window.veyra.chooseDataset(dataset);if(!response)return;catalog=response.result??response;const first=catalog!.sequences?.find((s:Json)=>s.frames>0);sequence=first?.id??'';config={...config,dataset,dataset_root:catalog!.root,sequence};refreshText();notice=first?'Dataset inspected. Select a sequence, then open its preview.':'No supported frames found. Check the dataset format and selected directory.';});}
 async function configure(){
  await action(async()=>{
   const next=JSON.parse(configText||JSON.stringify(config));
   await window.veyra.validateConfig(next);
   const response=await window.veyra.configure(next);
   config=next;syncGovernorOverride(next.map?.governor_override);
   if(response.status)status=response.status;
   clearSessionView();awaitingFrame=true;workspace='Map';
   notice='Processing the first frame…';
   const first=await window.veyra.command('step');
   if(first.status)status=mergeSessionStatus(status,first.status);
   notice=frame?'Preview received. Use Play to continue.':'Frame processed. Waiting for visualization…';
  });
 }
 function updateConfig(next:Json){config=next;refreshText();}
 function selectDataset(value:string){dataset=value;catalog=null;sequence='';updateConfig({...config,dataset,dataset_root:'',sequence:''});}
 function selectSequence(value:string){sequence=value;updateConfig({...config,sequence});}
 async function importConfig(){await action(async()=>{
  const loaded=await window.veyra.openConfig();if(!loaded)return;
  config=loaded;dataset=loaded.dataset??dataset;sequence=loaded.sequence??'';
  catalog=null;preset=loaded.preset??'LowResource';
  syncGovernorOverride(loaded.map?.governor_override);refreshText();
  notice='Preset loaded. Choose its dataset directory to confirm the available sequence.';
 });}
 async function openDirect(){await configure();}
 function applyPreset(){config=profileConfig(config,preset);governorOverride='automatic';refreshText();}
 onMount(()=>{
  refreshText();if(!window.veyra){error=nativeRuntimeUnavailableMessage;return;}
  void action(async()=>{info=await window.veyra.info();if(info.status)status=info.status;});
  const off=window.veyra.onEvent(event=>{
   events=recordEvent(events,event);
   const diagnostic=diagnosticMessage(event);if(diagnostic){error=diagnostic;awaitingFrame=false;}
   if(event.type==='status'){status={...status,...event};if(event.error)error=event.error.process+': '+event.error.message;}
   if(event.type==='telemetry'){telemetry=event;const latency=event.latency_ms??{},rss=processRss(event.processes??[]);samples=[...samples,{timestamp:event.timestamp,fps:event.fps,p95:latency.end_to_end?.p95,rss:rss===null?null:rss/1048576,mapping:latency.mapping,perception:latency.perception}].slice(-300);}
   if(event.type==='desktop_telemetry')desktop=event;
   if(event.type==='benchmark'){benchmarkState=event.state;if(event.report)report=event.report;if(event.error)error=String(event.error.message??event.error);}
   if(event.type==='validation'){validationState=validationOutcome(event);if(event.result)validationResult=event.result;}
  });
  const offVisual=window.veyra.onVisualization(value=>{try{if(!acceptFrame(value,frame,status.state,awaitingFrame))return;frame=value;awaitingFrame=false;notice='';}catch(e){error=`Visualization failed: ${e instanceof Error?e.message:String(e)}`;awaitingFrame=false;}});
  const clock=setInterval(()=>{now=Date.now();},1000);
  const subscriptionError=(event:Event)=>{error=`Desktop event connection failed: ${(event as CustomEvent).detail}`;};
  window.addEventListener('veyra-subscription-error',subscriptionError);
  return()=>{off();offVisual();clearInterval(clock);window.removeEventListener('veyra-subscription-error',subscriptionError);};
 });
</script>

<div class="application">
 <aside class="rail">
  <div class="brand"><img class="brand-logo" src={veyraLogo} alt="Veyra logo"/><span>VEYRA<small>Map smarter.<br/>Move safer.</small></span></div>
  <nav aria-label="Workspaces">{#each [['Dashboard','Overview','home'],['Map','Viewer','map'],['Datasets','Session setup','database'],['Performance','Performance','chart'],['Benchmarks','Evaluation','check']] as [key,name,icon]}<button class:active={workspace===key} aria-current={workspace===key?'page':undefined} onclick={()=>workspace=key}><Icon name={icon}/>{name}</button>{/each}</nav>
  <div class="rail-bottom"><div class="rail-session"><span class="runtime-dot" class:online={sessionActive(status)}></span><div><strong>{runtimeLabel(status.state)}</strong><small>{status.dataset?status.dataset+' · '+(status.sequence??''):'Choose a source to begin'}</small></div></div><span class="muted">Veyra {info.version??'0.1.0'}</span></div>
 </aside>
 <main>
  <header>
   <div class="header-title"><div><h1>{workspace==='Dashboard'?'Overview':workspace==='Map'?'Viewer':workspace==='Performance'?'Performance':workspace==='Benchmarks'?'Evaluation':'Session setup'}</h1><span class="status-pill" class:running={status.state==='running'} class:failed={status.state==='error'}><i></i>{runtimeLabel(status.state)}</span>{#if liveStale}<span class="stale-badge" title="Values are last measured, not live.">Last measured · {staleAge??'stale'}</span>{/if}</div><p>{workspace==='Datasets'?'Configure a source and open its first frame.':workspace==='Benchmarks'?'Compare map quality against measured resource cost.':workspace==='Performance'?'Measured pipeline, process and map resources.':'Adaptive semantic 2.5D mapping'}</p></div>
   <div class="header-right"><div class="session-label"><Icon name="database" size={17}/><span id="header-scenario">{status.sequence?status.dataset+' · '+status.sequence:'No dataset selected'}</span></div><button class="export-button" disabled={busy} title="Export runtime configuration, recent errors and diagnostics" onclick={()=>action(async()=>{const saved=await window.veyra.diagnostics();confirmSaved(saved,'Diagnostics exported.','Diagnostics export cancelled — no file written.');})}><Icon name="export" size={17}/>Diagnostics</button></div>
  </header>
  {#if error}{@const recovery=errorRecovery(error)}<div class="alert" role="alert"><div class="alert-content"><strong>{recovery.title}</strong><p>{recovery.action}</p><details><summary>Technical detail</summary><pre>{error}</pre></details></div>{#if recovery.restart}<button disabled={busy} onclick={restartRuntime}>Restart runtime</button>{:else}<button disabled={busy} onclick={()=>workspace='Datasets'}>Review setup</button>{/if}<button aria-label="Dismiss error" onclick={()=>error=''}><Icon name="close" size={18}/></button></div>{/if}
  {#if notice}<div class="notice" role="status">{notice}</div>{/if}
  {#if workspace==='Dashboard'}
   <Dashboard {status} {telemetry} {frame} {report} {events} {busy} {awaitingFrame} openDataset={()=>workspace='Datasets'} openPerformance={()=>workspace='Performance'} openMap={()=>workspace='Map'} openBenchmarks={()=>workspace='Benchmarks'}/>
  {:else if workspace==='Map'}
   <div class="map-workspace">
    <aside class="layer-panel"><div class="panel-heading">VIEW <span>RAW / MAP</span></div>
     <div class="segmented" role="group" aria-label="Raw and map visibility">{#each [['raw','Raw'],['both','Both'],['map','Map']] as [value,label]}<button class:active={viewMode===value} onclick={()=>setViewMode(value)}>{label}</button>{/each}</div>
     <p class="hint">Raw LiDAR points vs adaptive 2.5D map cells — never the same thing.</p><label class="accumulate" title="Display only: overlays recent pose-aligned scans. The mapper still receives one scan per frame.">Accumulate<select bind:value={accumulate} disabled={viewMode==='map'}>{#each [[1,'off'],[10,'10 scans'],[20,'20 scans'],[50,'50 scans']] as [value,label]}<option value={value}>{label}</option>{/each}</select></label><div class="separator"></div>
     <div class="panel-heading">LAYERS <span>DISPLAY</span></div>
     {#each [['semantic','Semantic'],['elevation','Elevation'],['ground','Ground'],['terrain','Traversability'],['motion','Motion'],['lod','LOD resolution'],['utility','Utility']] as [value,label]}
      <button class="layer" class:selected={mode===value} onclick={()=>setLayer(value)} disabled={!playbackEnabled()} title={value==='lod'?'Cell size by level: L0 5 cm, L1 10 cm, L2 20 cm, L3 40 cm':value==='utility'?'Per-cell promotion signal 0–1 (quality-gated)':label}><span class="layer-dot" style:background={value==='lod'?'#45d3c9':undefined}></span>{label}{#if layerUnavailable(frame,value)}<small>n/a</small>{/if}</button>
     {/each}
     <div class="separator"></div><label class="toggle"><input type="checkbox" bind:checked={boundaries}/>Cell boundaries</label><label class="toggle"><input type="checkbox" bind:checked={follow}/>Follow robot</label><label class="toggle" title="DistanceLOD bands: 0–10 m → 5 cm, 10–30 m → 10 cm, 30–60 m → 20 cm, 60–100 m → 40 cm"><input type="checkbox" bind:checked={showRings}/>Range rings</label>
     <div class="panel-heading space-top" title={GLOSSARY['LOD']}>RESOLUTION <span title={GLOSSARY['LOD']}><Icon name="info" size={14}/></span></div>{#each ['5 cm','10 cm','20 cm','40 cm'] as level,i}<div class="legend-row"><i style:background={['#33d9f2','#4dd980','#ffb340','#d966d9'][i]}></i><span>L{i} · {level}</span><b>{format(telemetry.map?.cells_by_level?.[i],0)}</b></div>{/each}
     <div class="legend-row"><span>Splits / s</span><b>{format(telemetry.map?.splits_per_second,2)}</b></div><div class="legend-row"><span>Merges / s</span><b>{format(telemetry.map?.merges_per_second,2)}</b></div>
     {#if inspector}<div class="inspector"><div class="panel-heading">CELL INSPECTOR <span>MEASURED</span></div>{#each inspectorRows(inspector) as row}<div title={row.hint}><span>{row.label}</span><b>{row.value}</b></div>{/each}<button onclick={()=>inspector=null}>Close</button></div>{:else}<p class="hint">Click a map cell to inspect its stored XY + height/statistics.</p>{/if}
    </aside>
    <section class="map-stage" aria-label="LiDAR and adaptive map">
     {#if showCells}<div class="representation-banner" title={GLOSSARY['2.5D']}><strong>Representation · Adaptive 2.5D Grid</strong><span>Rendered in 3D · Stored as XY cells + height/statistics</span><details><summary>What is 2.5D?</summary><p>Veyra stores one adaptive XY cell containing height and scene statistics rather than maintaining a dense XYZ voxel volume. (X,Y) → elevation + statistics.</p></details></div>{/if}
     <MapCanvas {frame} {mode} {showPoints} {showCells} {boundaries} {view} {follow} {accumulate} {showRings} onStats={value=>render={...render,...value,updated_at:Date.now()}} onInspect={value=>inspector=value}/>
     <div class="map-toolbar"><div class="segmented">{#each ['orbit','top','driver'] as camera}<button class:active={view===camera} onclick={()=>view=camera}>{camera}</button>{/each}</div><span class="policy-badge" title="Active mapping policy driving the mapper — not just a dropdown state">Policy · {labels[status.policy]??status.policy??'—'}</span>
     {#if frame&&(mode==='semantic')}<div class="map-legend" aria-label="Semantic legend"><span class="legend-title">Classes · {frame?.metadata.pipeline_status?.semantic==='ground_truth'?'dataset ground truth':'model inference'}</span>{#each classNames.map((name,id)=>({name,id})).filter(item=>item.id!==0) as item}<span><i style:background={cssRGB(semanticRGB(item.id))}></i>{item.name}</span>{/each}<span><i style:background={cssRGB(semanticRGB(0))}></i>Unknown</span></div>{/if}
     {#if frame&&mode==='terrain'}<div class="map-legend" aria-label="Traversability legend"><span><i style:background="#33d980"></i>Drivable</span><span><i style:background="#f24d59"></i>Non-drivable</span><span><i style:background="#59616b"></i>Unknown — never drivable</span></div>{/if}
     {#if frame&&mode==='motion'}<div class="map-legend" aria-label="Motion legend"><span><i style:background="#336699"></i>STATIC</span><span><i style:background="#b35533"></i>MOVING</span><span><i style:background="#59616b"></i>UNKNOWN</span></div>{/if}<button disabled={!frame||busy} onclick={()=>action(async()=>{const saved=await window.veyra.screenshot();confirmSaved(saved,'Screenshot saved.','Screenshot cancelled — no file written.');})}><Icon name="camera" size={16}/>Screenshot</button></div>
     {#if !frame}<div class="map-empty" role="status"><h2>{error?'Preview unavailable':awaitingFrame?'Processing your first frame…':'Open a dataset to begin'}</h2><p>{error?'The error above explains what failed. Return to Dataset to check the session.':awaitingFrame?'The runtime is preparing LiDAR points and map cells. The preview appears when those bytes reach this viewer.':'Choose a dataset directory and sequence, then open its preview.'}</p>{#if !awaitingFrame}<button class="primary" onclick={()=>workspace='Datasets'}><Icon name="folder" size={18}/>Set up a session</button>{/if}</div>{/if}
     <div class="map-coordinate"><span>WORLD · ODOM</span><span>Frame {frame?.metadata.frame_id??status.index??'—'} · {frame?.metadata.dataset??status.dataset??'—'}/{frame?.metadata.sequence??status.sequence??'—'} · {format(frame?.metadata.n_points,0)} pts · {frame?.metadata.range_m?`≤ ${frame.metadata.range_m} m`:'full range'}</span><span>{format(render.source_points??frame?.metadata.points?.count,0)} source points · {format(render.rendered_points??frame?.metadata.points?.count,0)} rendered{#if (render.accumulated_scans??1)>1} from {render.accumulated_scans} scans{/if} · {format(render.source_cells??frame?.metadata.cells?.count,0)} source cells · {render.sampling_active?'SAMPLING ACTIVE':'FULL VIEW'}</span></div>
     {#if frame&&mode==='motion'&&layerUnavailable(frame,'motion')}<div class="layer-warning">Motion evidence unavailable for this dataset — no dataset timestamps, so nothing is tracked or drawn as moving. Static map evidence is unaffected.</div>
     {:else if frame&&layerUnavailable(frame,mode)}<div class="layer-warning">{mode[0].toUpperCase()+mode.slice(1)} values are unavailable in the current map snapshot.</div>{/if}
     <details class="event-drawer"><summary>Events / Diagnostics ({events.length})</summary><div class="event-list">{#each events.slice(-30).reverse() as event}<div class="event-item"><i class:error={event.kind==='error'}></i><time>{new Date(event.time).toLocaleTimeString(undefined,{hour12:false})}</time><p>{event.message}</p></div>{:else}<div class="events-empty">No runtime events yet.<span>Session changes and backend diagnostics appear here.</span></div>{/each}</div></details>
    </section>
   </div>
   <div class="playback"><div class="playback-buttons"><button title="Reset map" disabled={!playbackEnabled()} aria-label="Reset map" onclick={()=>command('reset')}><Icon name="restart" size={18}/></button><button class="play-button" disabled={!playbackEnabled()} aria-label={status.state==='running'?'Pause replay':'Play replay'} onclick={()=>command(status.state==='running'?'pause':'start')}><Icon name={status.state==='running'?'pause':'play'} size={18}/></button><button title="Step frame" disabled={!playbackEnabled()} aria-label="Next frame" onclick={()=>command('step')}><Icon name="next" size={18}/></button></div><div class="timeline"><div><span>FRAME {format(status.index,0)}</span><span>{format(status.frames,0)} frames</span></div><input aria-label="Seek frame" type="range" min="0" max={Math.max(0,(status.frames??1)-1)} value={status.index??0} oninput={event=>seekIndex=Number(event.currentTarget.value)} onchange={()=>command('seek',{index:seekIndex})} disabled={!playbackEnabled()}/></div><select disabled={!playbackEnabled()} aria-label="Playback speed" value={status.speed??1} onchange={event=>command('speed',{speed:Number(event.currentTarget.value)})}>{#each [.25,.5,1,2,4,8] as speed}<option value={speed}>{speed}×</option>{/each}</select><select disabled={!playbackEnabled()} aria-label="Mapping policy" value={status.policy??'distance_lod'} onchange={event=>command('policy',{policy:event.currentTarget.value})}>{#each policies as policy}<option value={policy}>{labels[policy]}</option>{/each}</select></div>
   <div class="metric-strip">
    <div title="Completed backend frame throughput"><span>Processing</span><b>{proc.label}</b><small>{proc.sub}</small></div>
    <div title="Latest measured C++ map-update latency"><span>Map update</span><b>{format(telemetry.latency_ms?.mapping,2)} <small>ms</small></b></div>
    <div title="Live C++ logical map bytes"><span>Map memory</span><b>{mb(telemetry.map?.logical_bytes)}</b></div>
    <div title="OS-measured C++ mapper process RSS"><span>Mapper RSS</span><b>{mb(telemetry.processes?.find((p:Json)=>p.name==='mapper')?.rss_bytes)}</b></div>
    <div><span>Active cells</span><b>{format(telemetry.map?.active_cells,0)}</b></div>
    <div title="Three.js viewport throughput"><span>Render FPS{#if isRenderStale(render)} · stale{/if}</span><b>{format(render.fps)}</b></div>
    <div title="Processing drops; visualization supersession is reported separately"><span>Dropped frames</span><b>{format(telemetry.dropped_frames,0)}</b></div>
   </div>
  {:else if workspace==='Performance'}
   <div class="workspace-scroll performance-page"><div class="page-intro"><div><h2>Every stage, accounted for.</h2><p>Live process measurements. Rolling history retains the latest 300 samples.</p></div><span class="chip">{status.config_digest?.slice(0,12)??'NO SESSION'}</span></div>
   <TelemetrySummary {telemetry} renderer={render} {now} />
    <div class="stats-grid"><div class="stat-card" title="Actual completed backend frame throughput; state-aware, never measured zero."><span>PROCESSING</span><strong>{proc.label}</strong><small>{proc.sub}</small></div>{#each [['ROLLING E2E p50','p50',MIN_SAMPLES.p50],['ROLLING E2E p95','p95',MIN_SAMPLES.p95],['ROLLING E2E p99','p99',MIN_SAMPLES.p99]] as [label,key,minimum]}{@const stat=e2eStat(String(key),Number(minimum))}<div class="stat-card" title="Rolling backend end-to-end latency over the last 600 completed frames — same canonical source as Live Mapping CURRENT E2E p95."><span>{label}</span><strong>{stat.text} <small>ms</small></strong><small>{lastMeasured()}{stat.sub}</small></div>{/each}</div>
    <section class="card workload" aria-label="Measurement workload"><h3>Workload <span>{liveStale?'LAST MEASURED':'LIVE'}</span></h3><div class="data-row"><span>Dataset · sequence</span><b>{status.dataset??'—'}{status.sequence?' · '+status.sequence:''}</b></div><div class="data-row"><span>Policy · frames</span><b>{labels[status.policy]??status.policy??'—'} · {format(status.index,0)} / {format(status.frames,0)}</b></div><div class="data-row"><span>Semantic source</span><b>{telemetry.perception?.provider??'—'}</b></div><div class="data-row"><span>Execution</span><b>{telemetry.perception?.execution_provider??'—'}</b></div><div class="data-row"><span>Build · config</span><b>{status.build_mode??'—'} · {status.config_digest?.slice(0,12)??'NO SESSION'}</b></div><p class="hint">Identical workload fields must accompany every cross-hardware screenshot. Points/frame and commit travel with benchmark artifacts.</p></section>
    <div class="chart-grid"><section class="card"><h3>Throughput <span>FPS</span></h3><Chart {samples} metric="fps" label="Processing FPS"/></section><section class="card"><h3>End-to-end latency <span>p95 · ms</span></h3><Chart {samples} metric="p95" label="Frame p95" color="#c29cff"/></section><section class="card"><h3>Backend process memory <span>RSS · MB</span></h3><Chart {samples} metric="rss" label="Python + mapper RSS" color="#ffba6b"/></section><section class="card"><h3>Mapper latency <span>ms</span></h3><Chart {samples} metric="mapping" label="Mapping" color="#78b9ff"/></section></div>
    <div class="two-columns"><section class="card"><h3>Processes <span>CPU / memory</span></h3><table><thead><tr><th>Process</th><th>PID</th><th>CPU</th><th>RSS</th></tr></thead><tbody>{#each [...(telemetry.processes??[]),...(desktop.processes??[])] as process}<tr><td>{process.name}</td><td>{process.pid??'—'}</td><td>{format(process.cpu_percent)}%</td><td>{mb(process.rss_bytes)}</td></tr>{/each}</tbody></table><p class="hint">CPU may exceed 100% across cores. Unavailable measurements display —. {FIRST_CPU_SAMPLE_NOTE} Python rows are measured per frame by the Python reporter; desktop process rows are emitted only when the native shell can measure them. {MEMORY_DOMAIN_NOTE}</p></section><section class="card"><h3>Frame stages <span>ms</span></h3>{#each [['Perception',telemetry.latency_ms?.perception],['Bridge / IPC',telemetry.latency_ms?.ipc],['C++ mapping',telemetry.latency_ms?.mapping],['Visualization preparation',telemetry.latency_ms?.visualization],[`Renderer${isRenderStale(render,now)?' · STALE':''}`,render.latency_ms],...Object.entries(telemetry.perception_stages_ms??{})] as [label,value]}<div class="data-row"><span>{label}</span><b>{format(value,2)}</b></div>{/each}<p class="hint">Renderer values come from the Map viewport (~1 s Three.js window). Last update: {render?.updated_at?new Date(render.updated_at).toLocaleTimeString(undefined,{hour12:false}):'—'}{render?.updated_at?` (${formatRenderAge(render)})`:''}; values persist after leaving Map and are marked stale off-Map.</p></section></div>
    <section class="card perception-status"><h3>Perception evidence <span>{frame?.metadata.dataset??'NO FRAME'}</span></h3><div class="stage-grid">{#each perceptionStages(frame) as stage}<div class="stage-item"><span>{stage.label}</span><strong class:stage-available={stage.status==='available'||stage.status==='model'||stage.status==='ground_truth'} class:stage-unavailable={stage.status==='unavailable'||stage.status==='invalid'}>{stage.status}</strong><small>{format(stage.latency,2)} ms</small></div>{/each}</div><p class="hint">Status is reported by the active pipeline; unavailable and skipped evidence is never rendered as measured data.</p></section>
    <div class="two-columns"><section class="card"><h3>Map allocation</h3>{#each mapActivity(telemetry) as [label,value]}<div class="data-row"><span>{label}</span><b>{label.includes('bytes')?mb(value):format(value,label.includes('second')?2:0)}</b></div>{/each}<p class="hint">{MEMORY_DOMAIN_NOTE} Map allocation shows live C++ snapshot bytes; compare only within this card.</p></section><section class="card"><h3>Resource governor <span>{telemetry.governor?.state??'unavailable'}</span></h3><label for="governor-override">Manual override</label><select id="governor-override" aria-label="Governor override" value={governorOverride} title={busy?'Governor control unavailable while a command is running.':!status.frames?'Configure a dataset session before overriding the governor.':'Manual governor override. Backend state is shown above.'} disabled={!playbackEnabled()} onchange={event=>{void setGovernor(event.currentTarget.value);}}><option value="automatic">Automatic</option><option value="disabled">Disabled (debug)</option><option value="conserve">Conserve resources</option></select><div class="data-row"><span>Queue depth</span><b>{format(telemetry.queue_depth,0)}</b></div><div class="data-row"><span>Dropped frames</span><b>{format(telemetry.dropped_frames,0)}</b></div><div class="data-row"><span>Visualization superseded</span><b>{format(telemetry.visualization_dropped,0)}</b></div><div class="data-row"><span>Desktop updates superseded</span><b>{format(desktop.ui_visualization_dropped,0)}</b></div>{#if desktop.ui_visualization_dropped==null}<p class="hint">Desktop shell counter unavailable — this shell emits no desktop_telemetry (Tauri).</p>{/if}<pre>{JSON.stringify(telemetry.governor?.budget??{budget:'unavailable'},null,2)}</pre></section></div>
   </div>
  {:else if workspace==='Benchmarks'}
   <div class="workspace-scroll">
   <ComparisonEvidence {report} />
   <section class="card runtime-actions"><h3>Session validation <span>{validationState.toUpperCase()}</span></h3><p class="hint">Runs the configured real dataset frame through perception and the mapper. It is a live smoke validation, not a replacement for repository CI.</p><button class="primary" disabled={busy||!sessionActive(status)} onclick={runValidation}>Run session validation</button>{#if validationResult}<table><tbody>
      <tr><td>Result</td><td><strong>{String(validationResult.status??validationState).toUpperCase()}</strong> (real validator — never fabricated)</td></tr>
      <tr><td>Dataset / sequence</td><td>{validationResult.dataset??status.dataset??'—'} / {validationResult.sequence??status.sequence??'—'}</td></tr>
      <tr><td>Frame / points</td><td>{validationResult.frame??'—'} / {format(validationResult.points,0)}</td></tr>
      <tr><td>Semantic / ground / terrain</td><td>{validationResult.semantic??'—'} / {validationResult.ground??'—'} / {validationResult.terrain??'—'}</td></tr>
      <tr><td>Map</td><td>{validationResult.map??'—'}</td></tr>
      <tr><td>Policy</td><td>{labels[status.policy]??status.policy??'—'}</td></tr>
      <tr><td>Elapsed</td><td>{format(validationResult.elapsed_ms,1)} ms</td></tr>
      <tr><td>Commit / hardware</td><td>{info.commit??'N/A'} / {info.platform??'N/A'}</td></tr>
     </tbody></table><details><summary>Raw validator output</summary><pre>{JSON.stringify(validationResult,null,2)}</pre></details>{/if}</section>
   <div class="page-intro"><div><h2>Quality has a resource cost.</h2><p>Compare all four policies using the same report schema as CI.</p></div><span class="chip" title={measurementDisplay(benchmarkState).sub}>{measurementDisplay(benchmarkState).label}</span></div><section class="card benchmark-controls"><div><label for="benchmark-count">Frames</label><input id="benchmark-count" type="number" min="1" max="100000" bind:value={benchmarkCount}/></div><button class="primary" disabled={busy||!sessionActive(status)} onclick={runBenchmark}>Run four-policy benchmark</button><button onclick={()=>action(async()=>{const loaded=await window.veyra.openReport();if(loaded){previousReport=report;report=loaded;}})}>Open report</button><button disabled={!report} onclick={()=>action(async()=>{const saved=await window.veyra.exportReport(report!);confirmSaved(saved,'Benchmark report exported.','Benchmark export cancelled — no file written.');})}>Export JSON</button><button onclick={()=>action(async()=>{previousReport=await window.veyra.openReport();})}>Compare previous run</button></section>
    {#if report}{#if previousReport}<section class="card"><h3>Previous run comparison</h3><table><thead><tr><th>Policy</th><th>Current bench p95</th><th>Previous bench p95</th><th>Current RMSE</th><th>Previous RMSE</th></tr></thead><tbody>{#each rows(report) as [policy,result]}{@const previous=rows(previousReport).find(([key])=>key===policy)?.[1]}<tr><td>{labels[policy]??policy}</td><td>{format(result.aggregate?.stage_latency_ns?.map_update?.p95/1e6)} ms</td><td>{format(previous?.aggregate?.stage_latency_ns?.map_update?.p95/1e6)} ms</td><td>{format(quality(result),4)}</td><td>{previous?format(quality(previous),4):'—'}</td></tr>{/each}</tbody></table></section>{/if}<details class="card"><summary>Full benchmark artifact</summary><pre>{JSON.stringify(report,null,2)}</pre></details>{:else}<div class="blank-card"><Icon name="file" size={32}/><h2>No benchmark loaded</h2><p>Configure a dataset session, then run a measured comparison.<br/>Existing JSON artifacts can be opened at any time.</p></div>{/if}
   </div>
  {:else}
   <SessionSetup {catalog} {status} {config} bind:configText {dataset} {sequence} {preset} {busy}
    onDataset={selectDataset} onSequence={selectSequence} onConfig={updateConfig}
    onPreset={value=>{preset=value;applyPreset();}} {chooseDataset} openPreview={openDirect}
    {importConfig} validateConfig={()=>action(async()=>{await window.veyra.validateConfig(JSON.parse(configText));notice='Configuration is valid.';})}
    saveConfig={()=>action(async()=>{const saved=await window.veyra.saveConfig(JSON.parse(configText));confirmSaved(saved,'Preset saved.','Preset save cancelled — no file written.');})}
    {stopRuntime} {restartRuntime}/>

  {/if}
 </main>
</div>
