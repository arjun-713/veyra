<script lang="ts">
  import type {Json} from '../core';
  import {comparisonScope} from './benchmark-report';
  import {formatAxisValue, latencyAxisLabel, niceAxis, placePointLabels, POLICY_COLORS, PUBLIC_POLICY_LABELS, qualityMetricDirection, qualityParetoPolicies, qualityPlotPoints, type QualityMetric} from './benchmark-quality';
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
  const PLOT = {left: 65, right: 444, top: 50, bottom: 220};
  const LABEL_BOX = {left: 66, right: 476, top: 32, bottom: 219};
  const isPercent = (selected: QualityMetric) => selected === 'heightAccuracy' || selected === 'completion';
  function shown(value: number, selected: QualityMetric) {
    return isPercent(selected) ? value * 100 : value * 1000;
  }
  function yAxis(points: {y:number}[], selected: QualityMetric) {
    return isPercent(selected) ? niceAxis(100) : niceAxis(Math.max(...points.map(point => shown(point.y, selected))) * 1.1);
  }
  // Lower-is-better metrics put zero at the top so "up" always means better.
  function yFor(shownValue: number, max: number, selected: QualityMetric) {
    const normalized = Math.max(0, Math.min(1, shownValue / max));
    const progress = qualityMetricDirection(selected) === 'lower' ? 1 - normalized : normalized;
    return PLOT.bottom - progress * (PLOT.bottom - PLOT.top);
  }
  function xFor(value: number, max: number) { return PLOT.left + Math.max(0, Math.min(1, value / max)) * (PLOT.right - PLOT.left); }
  function xUnit(resource: string) {
    return resource === 'rss' ? 'Peak RSS memory (MB) ↓'
      : resource === 'latency' ? latencyAxisLabel(report)
        : 'Active map cells ↓';
  }
  const unitSuffix = (resource: string) => resource === 'rss' ? ' MB' : resource === 'latency' ? ' ms' : ' cells';
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
      {@const selected = plot.metric as QualityMetric}
      {@const xAxis = niceAxis(Math.max(...points.map(point => point.x), 0) * 1.1)}
      {@const yScale = yAxis(points, selected)}
      {@const marks = points.map(point => ({...point, cx: xFor(point.x, xAxis.max), cy: yFor(shown(point.y, selected), yScale.max, selected)}))}
      {@const labels = placePointLabels(marks, LABEL_BOX)}
      <div class="tradeoff-plot">
        <h4>{plot.title}</h4>
        {#if points.length}
          <svg viewBox="0 0 480 275" role="img" aria-label={`${titles[selected]} versus ${xUnit(plot.resource)}`}>
            <title>{titles[selected]} versus {xUnit(plot.resource)}</title>
            {#each yScale.ticks as tick}
              <line class="grid-y" x1={PLOT.left} x2={PLOT.right} y1={yFor(tick, yScale.max, selected)} y2={yFor(tick, yScale.max, selected)} stroke="var(--line)"/>
              <text class="tick-y" x="53" y={yFor(tick, yScale.max, selected)+4} text-anchor="end">{formatAxisValue(tick)}</text>
            {/each}
            {#each xAxis.ticks as tick}
              <text class="tick-x" x={xFor(tick, xAxis.max)} y="238" text-anchor="middle">{formatAxisValue(tick)}</text>
            {/each}
            <path d={`M${PLOT.left} ${PLOT.top-2}V${PLOT.bottom}H${PLOT.right}`} fill="none" stroke="var(--secondary)"/>
            <text class="axis-title-y" x={PLOT.left} y="25">{titles[selected]}</text>
            <text class="axis-title-x" x={(PLOT.left+PLOT.right)/2} y="262" text-anchor="middle">{xUnit(plot.resource)}</text>
            {#each marks as point}
              {@const onFrontier = frontier.includes(point.policy)}
              {#if onFrontier}<circle cx={point.cx} cy={point.cy} r="9" fill="none" stroke={POLICY_COLORS[point.policy]} stroke-width="1.5"/>{/if}
              <circle cx={point.cx} cy={point.cy} r="5" fill={POLICY_COLORS[point.policy]} fill-opacity="0.85"><title>{PUBLIC_POLICY_LABELS[point.policy]} · {format(point.x)}{unitSuffix(plot.resource)} · {format(shown(point.y,selected))}{isPercent(selected)?'%':' mm'}{onFrontier?' · Pareto-optimal':''}</title></circle>
            {/each}
            {#each labels as label}
              <text class="point-label" x={label.x} y={label.y} text-anchor={label.anchor} style:fill={POLICY_COLORS[label.policy]}>{label.text}</text>
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
