<script lang="ts">
  import type {Json} from '../core';
  import {PUBLIC_POLICY_LABELS} from './benchmark-quality';
  import QualityTradeoff from './QualityTradeoff.svelte';
  import StorageComparison from './StorageComparison.svelte';
  import {
    comparisonScope, mebibytes, millimetres, millis, percent, qualityResourceRows,
    referenceBaselines, reportProvenance, semanticQuality, type AcceptedReport, type QualityResourceRow,
  } from './benchmark-report';
  let {report = null, meta = null} = $props<{report?: Json | null; meta?: Omit<AcceptedReport, 'report'> & {artifactSha256?: string | null} | null}>();
  const rows = $derived(qualityResourceRows(report));
  const baselines = $derived(referenceBaselines(report));
  const semantic = $derived(semanticQuality(report));
  const provenance = $derived(reportProvenance(report));
  const scope = $derived(comparisonScope(report));
  const number = (value: number | null, decimals = 0) => value === null ? '—' : value.toLocaleString(undefined, {maximumFractionDigits: decimals});
  const evidence = (row: QualityResourceRow) => row.source === 'absent' ? 'UNAVAILABLE' : row.status.toUpperCase();
  const tail = (value: number | null, reliable: boolean) => value === null ? '—' : reliable ? millis(value) : `${millis(value)} (descriptive)`;
  const digests = $derived(Object.values(scope.inputDigests));
  const inputIdentity = $derived(scope.sameInput === true && digests.length === 4 ? `identical input · stream ${digests[0].slice(0, 12)}` : scope.sameInput === false ? 'INPUTS DIFFER — not comparable' : 'shared input not verified');
  const retention = (row: QualityResourceRow) => [['Ped', row.pedestrianRetention], ['Veh', row.vehicleRetention], ['Pole', row.poleRetention]]
    .filter(([, value]) => value !== null).map(([label, value]) => `${label} ${percent(value as number, 0)}`).join(' · ') || '—';
  const identity = $derived(provenance.gitSha ? provenance.gitSha.slice(0, 12) + (provenance.workingTreeDirty ? ' · dirty tree' : provenance.workingTreeDirty === false ? ' · clean' : '') : 'Unavailable');
</script>

{#if report}
<section class="card report-provenance" aria-label="Benchmark provenance">
  <h3>Report provenance<span>{meta?.origin === 'generated' ? 'GENERATED THIS SESSION' : 'OPENED FROM FILE'} · {meta?.complete ? 'COMPLETE' : 'INCOMPLETE'}</span></h3>
  <div class="provenance-grid">
    <div class="data-row"><span>Commit</span><b title={provenance.sourceStateSha256 ? `source state ${provenance.sourceStateSha256}` : undefined}>{identity}</b></div>
    <div class="data-row"><span>Input</span><b>{scope.dataset ?? '—'} · {scope.sequence ?? '—'} · frames {number(provenance.frameStart)}–{provenance.frameStart !== null && provenance.frameCount !== null ? number(provenance.frameStart + provenance.frameCount - 1) : '—'}</b></div>
    <div class="data-row"><span>Repetitions · warmup</span><b>{number(provenance.repetitions)} · {number(provenance.warmupFrames)} frames</b></div>
    <div class="data-row"><span>Perception</span><b>{provenance.perceptionExecuted === null ? '—' : provenance.perceptionExecuted ? 'executed' : 'skipped (source labels sent to map)'}</b></div>
    <div class="data-row"><span>Host</span><b>{provenance.processor ?? '—'}{provenance.memoryBytes !== null ? ' · ' + mebibytes(provenance.memoryBytes, 0) : ''}</b></div>
    <div class="data-row"><span>Build · recorded</span><b>{provenance.buildType ?? '—'} · {provenance.timestampUtc ?? '—'}</b></div>
  </div>
  {#if meta?.issues?.length}<ul class="report-issues">{#each meta.issues as issue}<li>{issue}</li>{/each}</ul>{/if}
</section>
{/if}

<section class="card comparison-evidence" aria-label="Policy comparison evidence">
  <h3>Policy comparison<span>{scope.dataset ?? '—'} · {scope.sequence ?? '—'} · {number(scope.frameCount)} frames · {inputIdentity}</span></h3>
  <p class="hint">All four production policies replayed the same observations in one benchmark run. Map quality and resource cost belong together; each row identifies its evidence.</p>
  {#if scope.sameInput === false}<p class="report-warning">The policies did not consume identical input streams, so these rows are not a like-for-like comparison.</p>{/if}
  <p class="direction-legend"><span>↓ lower is better</span><span>↑ higher is better</span><span>— not measured in this report (never zero)</span><span>MEASURED · ANALYTICAL · UNAVAILABLE = evidence type</span></p>
  <div class="table-wrap"><table>
    <thead><tr><th>Policy</th><th>Evidence</th><th>Logical map ↓</th><th>Mapper peak RSS ↓</th><th>Active cells ↓</th><th>Map update {scope.latencyMetric} ↓</th><th>Height accuracy ≤10 cm ↑</th><th>Completion ↑</th><th>Surface Chamfer ↓</th><th>Critical retention ↑</th></tr></thead>
    <tbody>
      {#each rows as row}
        <tr><td><strong>{PUBLIC_POLICY_LABELS[row.policy]}</strong></td><td><span class="chip">{evidence(row)}</span></td><td>{mebibytes(row.logicalBytes)}</td><td>{mebibytes(row.rssBytes)}</td><td>{number(row.activeCells)}</td><td>{scope.latencyMetric === 'p95' ? millis(row.mapP95Ms) : millis(row.mapP50Ms)}</td><td>{percent(row.heightAccuracy10)}</td><td>{percent(row.completion)}</td><td>{millimetres(row.chamferM)}</td><td>{retention(row)}</td></tr>
      {/each}
      {#each baselines as baseline}
        <tr><td><strong>{baseline.label}</strong></td><td><span class="chip">{baseline.kind.toUpperCase()}</span></td><td>{baseline.bytes === null ? '—' : (baseline.kind === 'analytical' ? 'est. ' : '') + mebibytes(baseline.bytes, 0)}</td><td colspan="7" class="baseline-detail">{baseline.detail}{baseline.cells !== null ? ` · ${number(baseline.cells)} ${baseline.key === 'uniform_5cm_2d' ? 'reference bins' : 'cells'}` : ''}</td></tr>
      {/each}
    </tbody>
  </table></div>
  <p class="hint">Surface metrics compare with observed Uniform5 support in the same region and coordinate frame{scope.referenceIsGroundTruth === false ? ' — explicitly not surveyed ground truth' : ''}. Mapper peak RSS is the C++ benchmark process and includes non-map overhead; logical memory describes the map itself. Map update uses p95 only when every policy has at least 20 samples, otherwise p50 ({number(rows[0]?.mapSamples ?? null)} samples per policy here). Critical retention is the fraction of pedestrian, vehicle and pole reference cells whose class survives in the map, shown only when measured (requires frame retention).</p>
  <details class="comparison-details"><summary>Reconstruction, retention and timing details</summary>
    <div class="table-wrap"><table><thead><tr><th>Policy</th><th>Input accuracy ↓</th><th>Input completion distance ↓</th><th>Input Chamfer ↓</th><th>Active cells</th><th>Elevation RMSE ↓</th><th>Semantic retention ↑</th><th>Vehicle retention ↑</th><th>FPS p50 ↑</th><th>Map p95 ↓</th><th>Map p99 ↓</th><th>Samples</th></tr></thead><tbody>
      {#each rows as row}
        <tr><td>{PUBLIC_POLICY_LABELS[row.policy]}</td><td>{millimetres(row.inputAccuracyM)}</td><td>{millimetres(row.inputCompletionM)}</td><td>{millimetres(row.inputChamferM)}</td><td>{number(row.activeCells)}</td><td>{row.rmseM === null ? '—' : number(row.rmseM, 4) + ' m'}</td><td>{percent(row.semanticRetention)}</td><td>{percent(row.vehicleRetention)}</td><td>{number(row.fpsP50, 2)}</td><td>{tail(row.mapP95Ms, row.p95Reliable)}</td><td>{tail(row.mapP99Ms, row.p99Reliable)}</td><td>{number(row.mapSamples)}</td></tr>
      {/each}
    </tbody></table></div>
    <p class="hint">Input reconstruction metrics measure nearest-neighbour distances to accepted input returns. Their definition differs from surface-support accuracy/completion. p95 requires at least 20 samples and p99 at least 100; below that the value equals a near-maximum and is labelled descriptive. Dense 3D estimates are analytical and have no measured timing.</p>
  </details>
</section>

{#if report}
<StorageComparison {report}/>
<section class="card semantic-quality" aria-label="Semantic segmentation quality">
  <h3>Semantic quality<span>{semantic.status === 'measured' ? 'MEASURED' : 'UNAVAILABLE'} · {semantic.groundTruth ? 'DATASET GROUND TRUTH' : semantic.source ? 'MODEL · ' + semantic.source.replaceAll('_', ' ').toUpperCase() : 'SOURCE UNRECORDED'}</span></h3>
  {#if semantic.status === 'measured' && semantic.groundTruth}<p class="report-warning">Semantic labels came from the dataset, not a neural model. These scores only confirm label plumbing and are not evidence of model accuracy.</p>{/if}
  {#if semantic.status === 'measured'}
    <div class="data-row"><span>Overall mIoU ↑</span><b>{percent(semantic.miou)}</b></div>
    <div class="data-row"><span>Point accuracy ↑</span><b>{percent(semantic.accuracy)} · {number(semantic.points)} points</b></div>
    {#if semantic.bins.length}<div class="table-wrap"><table><thead><tr><th>Range</th><th>mIoU ↑</th><th>Accuracy ↑</th><th>Points</th></tr></thead><tbody>
      {#each semantic.bins as bin}<tr><td>{number(bin.minM)}–{number(bin.maxM)} m</td><td>{percent(bin.miou)}</td><td>{percent(bin.accuracy)}</td><td>{number(bin.points)}</td></tr>{/each}
    </tbody></table></div>{/if}
    <p class="hint">Evaluated against {semantic.reference ?? 'dataset labels'} on the benchmarked selection.{provenance.perceptionExecuted === false ? ' Perception was skipped, so these scores do not measure a model.' : ''}</p>
  {:else}
    <p class="hint">{semantic.reason}. mIoU is never shown as zero when it was not measured.</p>
  {/if}
</section>
<QualityTradeoff {report}/>
{/if}
