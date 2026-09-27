<script lang="ts">
  import type {Json} from '../core';
  import {benchmarkEvidence} from './session';
  import {PUBLIC_POLICY_LABELS, policyQuality} from './benchmark-quality';
  import QualityTradeoff from './QualityTradeoff.svelte';
  import {gateStatistic, MIN_SAMPLES} from './dashboard';
  let {report = null} = $props<{report?: Json | null}>();
  const number = (value: unknown, decimals = 2) => typeof value === 'number' && Number.isFinite(value)
    ? value.toLocaleString(undefined, {maximumFractionDigits: decimals}) : '—';
  const bytes = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? number(value / 1048576, 1) + ' MB' : '—';
  const percent = (value: number | null) => value === null ? '—' : number(value * 100, 1) + '%';
  function rows() {
    const policies = (report?.mapping ?? report)?.policies ?? {};
    const result = Object.entries(PUBLIC_POLICY_LABELS).map(([key, label]) => ({
      key, label, status: policies[key] ? 'MEASURED' : 'UNAVAILABLE', value: (policies[key] ?? {}) as Json,
    }));
    const baselines = report?.baselines ?? report?.comparison ?? {};
    for (const key of ['measured_3d', 'measured_3d_baseline', 'analytical_3d', 'analytical_dense_reference']) {
      const value = baselines[key];
      if (value && typeof value === 'object') result.push({
        key, label: key.includes('analytical') ? 'Dense 3D reference' : 'Measured 3D baseline',
        status: key.includes('analytical') ? 'ANALYTICAL' : 'MEASURED', value,
      });
    }
    if (!result.some(row => row.key.includes('3d'))) result.push({
      key: '3d-unavailable', label: 'Measured 3D baseline', status: 'UNAVAILABLE', value: {},
    });
    return result;
  }
  const aggregate = (value: Json) => value.aggregate ?? value.metrics ?? value;
  function mapLatency(value: Json, key: 'p50' | 'p95' | 'p99') {
    const latency = aggregate(value).stage_latency_ns?.map_update ?? {};
    if (key === 'p50') return number(latency.p50 == null ? null : latency.p50 / 1e6);
    const statistic = gateStatistic(latency[key] == null ? null : latency[key] / 1e6, latency.count, MIN_SAMPLES[key]);
    return statistic.ok ? statistic.text : '—';
  }
  function retention(value: Json) {
    const quality = aggregate(value).quality;
    return (Array.isArray(quality) ? quality.at(-1) : quality)?.field_retention ?? {};
  }
  const fraction = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? number(value * 100, 1) + '%' : '—';
</script>

<section class="card comparison-evidence" aria-label="Policy comparison evidence">
  <h3>Policy comparison<span>Measured · Analytical · Unavailable</span></h3>
  <p class="hint">Map quality and resource cost belong together. Each row identifies its evidence; missing values remain unavailable.</p>
  <div class="table-wrap"><table>
    <thead><tr><th>Policy</th><th>Evidence</th><th>Logical map</th><th>Peak RSS</th><th>Map p50</th><th>Height accuracy ≤10 cm ↑</th><th>Completion ↑</th><th>Surface Chamfer ↓</th></tr></thead>
    <tbody>{#each rows() as row}
      {@const quality = policyQuality(row.value)}
      <tr><td><strong>{row.label}</strong></td><td><span class="chip">{row.status}</span></td><td>{bytes(benchmarkEvidence(row.value).logicalBytes)}</td><td>{bytes(aggregate(row.value).peak_rss_bytes)}</td><td>{mapLatency(row.value, 'p50')} ms</td><td>{percent(quality.heightAccuracy)}</td><td>{percent(quality.completion)}</td><td>{quality.surfaceChamfer === null ? '—' : number(quality.surfaceChamfer * 1000, 1) + ' mm'}</td></tr>
    {/each}</tbody>
  </table></div>
  <p class="hint">Surface metrics compare with observed Uniform5 support in the same region and coordinate frame. They are not surveyed ground truth. Peak RSS includes process overhead; logical memory describes the map itself.</p>
  <details class="comparison-details"><summary>Reconstruction, retention and timing details</summary>
    <div class="table-wrap"><table><thead><tr><th>Policy</th><th>Input accuracy ↓</th><th>Input completion distance ↓</th><th>Input Chamfer ↓</th><th>Active leaves</th><th>Elevation RMSE</th><th>Semantic retention</th><th>Vehicle retention</th><th>FPS p50</th><th>Map p95</th><th>Map p99</th></tr></thead><tbody>
      {#each rows() as row}
        {@const quality = policyQuality(row.value)}
        <tr><td>{row.label}</td><td>{quality.inputAccuracy === null ? '—' : number(quality.inputAccuracy * 1000) + ' mm'}</td><td>{quality.inputCompletion === null ? '—' : number(quality.inputCompletion * 1000) + ' mm'}</td><td>{quality.inputChamfer === null ? '—' : number(quality.inputChamfer * 1000) + ' mm'}</td><td>{number(benchmarkEvidence(row.value).leaves, 0)}</td><td>{number(benchmarkEvidence(row.value).rmse, 4)} m</td><td>{fraction(retention(row.value).semantic?.retention_fraction)}</td><td>{fraction(retention(row.value).task_classes?.members?.vehicle?.retention_fraction)}</td><td>{number(aggregate(row.value).fps?.p50)}</td><td>{mapLatency(row.value, 'p95')} ms</td><td>{mapLatency(row.value, 'p99')} ms</td></tr>
      {/each}
    </tbody></table></div>
    <p class="hint">Input reconstruction metrics measure nearest-neighbour distances to accepted input returns. Their definition differs from surface-support accuracy/completion. p95 requires at least 20 samples; p99 requires 100. Dense 3D estimates are analytical and have no measured timing.</p>
  </details>
</section>
{#if report}<QualityTradeoff {report}/>{/if}
