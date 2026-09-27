<script lang="ts">
  import type {Json} from '../core';
  import {latencyAxisLabel, PUBLIC_POLICY_LABELS, qualityPlotPoints, type QualityMetric} from './benchmark-quality';
  let {report} = $props<{report: Json | null}>();
  let metric = $state<QualityMetric>('heightAccuracy');
  const colors: Record<string, string> = {uniform5: '#64748b', uniform40: '#a76b12', distance_lod: '#0069df', utility_lod: '#188252'};
  const titles = {heightAccuracy: 'Height accuracy at 10 cm (%) ↑', completion: 'Completion (%) ↑', surfaceChamfer: 'Surface Chamfer (mm) ↓'};
  const displayY = (value: number) => value * (metric === 'surfaceChamfer' ? 1000 : 100);
  const format = (value: number) => value.toLocaleString(undefined, {maximumFractionDigits: 1});
</script>

<section class="card quality-tradeoff" aria-label="Map quality versus resource cost">
  <div class="tradeoff-heading"><div><h3>Map quality vs resource cost</h3><p class="hint">Same report, four production policies. Missing measurements are omitted.</p></div><select aria-label="Trade-off quality metric" bind:value={metric}><option value="heightAccuracy">Height accuracy at 10 cm</option><option value="completion">Completion</option><option value="surfaceChamfer">Surface Chamfer</option></select></div>
  <div class="tradeoff-grid">
    {#each ['memory', 'latency'] as resource}
      {@const points = qualityPlotPoints(report, resource as 'memory' | 'latency', metric)}
      {@const maxX = Math.max(1, ...points.map(point => point.x)) * 1.2}
      {@const maxY = metric === 'surfaceChamfer' ? Math.max(1, ...points.map(point => displayY(point.y))) * 1.15 : 100}
      <div class="tradeoff-plot">
        <h4>{resource === 'memory' ? 'Quality vs map memory' : 'Quality vs map-update time'}</h4>
        {#if points.length}
          <svg viewBox="0 0 480 275" role="img" aria-label={`${titles[metric]} versus ${resource === 'memory' ? 'logical map memory in MB' : latencyAxisLabel(report).replace(' ↓', '')}`}>
            <title>{titles[metric]} vs {resource}</title>
            {#each [0, .25, .5, .75, 1] as step}
              <line x1="65" x2="444" y1={220 - step * 170} y2={220 - step * 170} stroke="#ededf0"/>
              <text x="53" y={224 - step * 170} text-anchor="end">{format(maxY * step)}</text>
              <text x={65 + step * 379} y="242" text-anchor="middle">{format(maxX * step)}</text>
            {/each}
            <path d="M65 48V220H444" fill="none" stroke="#b5b5c0"/>
            <text x="65" y="25">{titles[metric]}</text>
            <text x="250" y="267" text-anchor="middle">{resource === 'memory' ? 'Logical map memory (MB) ↓' : latencyAxisLabel(report)}</text>
            {#each points as point, index}
              <circle cx={65 + point.x / maxX * 379} cy={220 - displayY(point.y) / maxY * 170} r="5" fill={colors[point.policy]}><title>{PUBLIC_POLICY_LABELS[point.policy]}: {format(point.x)} {resource === 'memory' ? 'MB' : 'ms'}, {format(displayY(point.y))} {metric === 'surfaceChamfer' ? 'mm' : '%'}</title></circle>
            {/each}
          </svg>
        {:else}<div class="plot-unavailable">Unavailable in this report</div>{/if}
      </div>
    {/each}
  </div>
  <div class="tradeoff-legend">{#each Object.entries(PUBLIC_POLICY_LABELS) as [policy, label]}<span><i style:background={colors[policy]}></i>{label}</span>{/each}</div>
  <p class="hint">Quality uses observed Uniform5 support, not surveyed ground truth. Higher accuracy/completion is better; lower Chamfer is better. Logical bytes exclude process overhead. Latency uses p95 only when every policy has at least 20 map-update samples; otherwise p50.</p>
</section>
