<script lang="ts">
  import type {Json} from '../core';
  import {comparisonScope} from './benchmark-report';
  import {latencyAxisLabel, POLICY_COLORS, PUBLIC_POLICY_LABELS, qualityMetricDirection, qualityParetoPolicies, qualityPlotPoints, type QualityMetric} from './benchmark-quality';
  let {report} = $props<{report: Json | null}>();
  let metric = $state<QualityMetric>('heightAccuracy');

  const titles: Record<QualityMetric, string> = {
    heightAccuracy: 'Height accuracy at 10 cm (%) ↑',
    completion: 'Observed-support completion (%) ↑',
    surfaceChamfer: 'Uniform5 surface Chamfer (mm) ↓',
    inputAccuracy: 'Input reconstruction accuracy distance (mm) ↓',
    inputCompletion: 'Input reconstruction completion distance (mm) ↓',
    inputChamfer: 'Input reconstruction Chamfer-L1 (mm) ↓',
  };
  const scopes = $derived(comparisonScope(report));
  function shown(value: number, selected: QualityMetric) {
    return (selected === 'surfaceChamfer' || selected === 'inputAccuracy' || selected === 'inputCompletion' || selected === 'inputChamfer' ? value * 1000 : value * 100);
  }
  function maxValue(points: {y:number}[], selected: QualityMetric) {
    return selected === 'heightAccuracy' || selected === 'completion' ? 100 : Math.max(1, ...points.map(point => shown(point.y, selected))) * 1.15;
  }
  function yPosition(value: number, max: number, selected: QualityMetric) {
    const normalized = Math.max(0, Math.min(1, shown(value, selected) / max));
    const progress = qualityMetricDirection(selected) === 'lower' ? 1 - normalized : normalized;
    return 220 - progress * 170;
  }
  function xUnit(resource: string) {
    return resource === 'rss' ? 'RSS memory (MB) ↓'
      : resource === 'latency' ? `${latencyAxisLabel(report)} (same benchmark run)`
        : 'Active map cells ↓';
  }
  function xScale(points: {x:number}[]) { return Math.max(1, ...points.map(point => point.x)) * 1.2; }
  function format(value: number) { return value.toLocaleString(undefined, {maximumFractionDigits: 1}); }
  function resourcePlots() {
    return [
      {key:'rss-quality', title:'Map quality vs measured RSS', resource:'rss', metric},
      {key:'latency-quality', title:'Map quality vs mapper latency', resource:'latency', metric},
      {key:'chamfer-rss', title:'Reconstruction Chamfer vs RSS', resource:'rss', metric:'inputChamfer' as QualityMetric},
      {key:'cells-quality', title:'Map quality vs active cells', resource:'activeCells', metric},
    ];
  }
</script>

<section class="card quality-tradeoff" aria-label="Map quality versus resource cost">
  <div class="tradeoff-heading">
    <div><h3>Map quality vs resource cost</h3><p class="hint">Offline benchmark comparison · same frames and input are required for a Pareto claim.</p></div>
    <label class="metric-select">Quality metric
      <select aria-label="Trade-off quality metric" bind:value={metric}>
        <option value="heightAccuracy">Height accuracy at 10 cm ↑</option>
        <option value="completion">Observed-support completion ↑</option>
        <option value="inputAccuracy">Reconstruction accuracy distance ↓</option>
        <option value="inputCompletion">Reconstruction completion distance ↓</option>
        <option value="inputChamfer">Reconstruction Chamfer-L1 ↓</option>
        <option value="surfaceChamfer">Uniform5 surface Chamfer ↓</option>
      </select>
    </label>
  </div>
  <p class="scope-state" class:scope-verified={scopes.status==='measured'&&scopes.sameInput===true}>
    {scopes.status==='measured'&&scopes.sameInput===true ? `MEASURED · IDENTICAL INPUT · ${scopes.dataset??'dataset'} ${scopes.sequence??''}` : 'PARTIAL / UNVERIFIED · no Pareto claim'}
  </p>
  <div class="tradeoff-grid">
    {#each resourcePlots() as plot}
      {@const points = qualityPlotPoints(report, plot.resource as 'rss'|'latency'|'activeCells', plot.metric as QualityMetric)}
      {@const frontier = qualityParetoPolicies(report, plot.resource as 'rss'|'latency'|'activeCells', plot.metric as QualityMetric)}
      {@const maxX = xScale(points)}
      {@const maxY = maxValue(points, plot.metric as QualityMetric)}
      {@const plotDirection = qualityMetricDirection(plot.metric as QualityMetric)}
      <div class="tradeoff-plot">
        <h4>{plot.title}</h4>
        {#if points.length}
          <svg viewBox="0 0 480 275" role="img" aria-label={`${titles[plot.metric as QualityMetric]} versus ${xUnit(plot.resource)}`}>
            <title>{titles[plot.metric as QualityMetric]} versus {xUnit(plot.resource)}</title>
            {#each [0, .25, .5, .75, 1] as step}
              <line x1="65" x2="444" y1={220-step*170} y2={220-step*170} stroke="var(--line)"/>
              <text x="53" y={224-step*170} text-anchor="end">{format(plotDirection==='lower'?maxY*(1-step):maxY*step)}</text>
              <text x={65+step*379} y="242" text-anchor="middle">{format(maxX*step)}</text>
            {/each}
            <path d="M65 48V220H444" fill="none" stroke="var(--secondary)"/>
            <text x="65" y="25">{titles[plot.metric as QualityMetric]}</text>
            <text x="250" y="267" text-anchor="middle">{xUnit(plot.resource)}</text>
            {#each points as point}
              {@const cx = 65 + point.x/maxX*379}
              {@const cy = yPosition(point.y,maxY,plot.metric as QualityMetric)}
              {@const onFrontier = frontier.includes(point.policy)}
              {#if onFrontier}<circle cx={cx} cy={cy} r="9" fill="none" stroke={POLICY_COLORS[point.policy]} stroke-width="1.5"/>{/if}
              <circle cx={cx} cy={cy} r="5" fill={POLICY_COLORS[point.policy]}><title>{PUBLIC_POLICY_LABELS[point.policy]} · {format(point.x)} {plot.resource==='rss'?'MB':plot.resource==='latency'?'ms':'cells'} · {format(shown(point.y,plot.metric as QualityMetric))} {plot.metric==='heightAccuracy'||plot.metric==='completion'?'%':'mm'}{onFrontier?' · Pareto-optimal':''}</title></circle>
            {/each}
          </svg>
          {#if scopes.status==='measured'&&scopes.sameInput===true}<p class="hint pareto-note">Ringed points are non-dominated for this resource and metric; no combined score.</p>{:else}<p class="hint pareto-note">Missing policy measurements are omitted. Incomplete input identity prevents a Pareto claim.</p>{/if}
        {:else}<div class="plot-unavailable">This metric/resource pair is unavailable in the loaded report.</div>{/if}
      </div>
    {/each}
  </div>
  <div class="tradeoff-legend">{#each Object.entries(PUBLIC_POLICY_LABELS) as [policy,label]}<span><i style:background={POLICY_COLORS[policy]}></i>{label}</span>{/each}</div>
  <p class="hint">Reconstruction distances compare each policy’s map to the same accepted world-frame input, voxel-averaged at 5 cm; they are not surveyed ground truth. Surface accuracy/completion/Chamfer use the observed Uniform5 support. Accuracy and completion distance, and Chamfer, are lower-is-better; percentage accuracy/completion are higher-is-better. Missing values stay unavailable.</p>
</section>
