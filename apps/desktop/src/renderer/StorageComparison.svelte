<script lang="ts">
  import type {Json} from '../core';
  import {POLICY_COLORS} from './benchmark-quality';
  import {mebibytes, storageComparison, timesSmaller, type StorageRow} from './benchmark-report';
  let {report = null} = $props<{report?: Json | null}>();
  const rows = $derived(storageComparison(report));
  // Dense 3D is orders of magnitude above the 2.5D maps, so bars use a
  // log10 scale over MB; the axis title says so.
  const PLOT = {left: 176, right: 452, top: 14, row: 30};
  const REFERENCE_COLORS: Record<string, string> = {dense_3d: '#9a3b3b', sparse_3d: '#6b4fa3'};
  const color = (row: StorageRow) => REFERENCE_COLORS[row.key] ?? POLICY_COLORS[row.key] ?? 'var(--secondary)';
  const mb = (bytes: number) => bytes / 1048576;
  const measuredMb = $derived(rows.filter(row => row.bytes !== null && row.bytes > 0).map(row => mb(row.bytes!)));
  const logMin = $derived(measuredMb.length ? Math.floor(Math.log10(Math.min(...measuredMb))) : 0);
  const logMax = $derived(measuredMb.length ? Math.max(logMin + 1, Math.ceil(Math.log10(Math.max(...measuredMb)))) : 1);
  const decades = $derived(Array.from({length: logMax - logMin + 1}, (_, index) => logMin + index));
  const xFor = (value: number) => PLOT.left + ((Math.log10(value) - logMin) / (logMax - logMin)) * (PLOT.right - PLOT.left);
  const decadeLabel = (power: number) => (10 ** power).toLocaleString(undefined, {maximumFractionDigits: Math.max(0, -power)});
  const height = $derived(PLOT.top + rows.length * PLOT.row + 46);
  const evidence = (row: StorageRow) => row.kind === 'measured' && row.key === 'sparse_3d' ? 'MEASURED COUNT' : row.kind.toUpperCase();
  const count = (value: number | null) => value === null ? 'unavailable' : value.toLocaleString(undefined, {maximumFractionDigits: 0});
  const bytes = (row: StorageRow, value: number | null) => value === null ? (row.key === 'dense_3d' && row.kind === 'analytical' ? 'not allocated' : 'unavailable') : `${row.kind === 'analytical' ? 'est. ' : ''}${mebibytes(value, value < 1048576 ? 3 : 1)}`;
</script>

<section class="card storage-comparison" aria-label="Storage: 3D versus 2.5D">
  <h3>Storage: 3D vs 2.5D<span>same accepted input · 5 cm 3D references</span></h3>
  <p class="hint">What a uniform high-resolution 3D map would cost beside each 2.5D policy. The dense grid is an analytical estimate that was never allocated; the sparse voxel hash counts occupied 5 cm voxels measured on the identical stream.</p>
  {#if measuredMb.length}
    <svg class="storage-bars" viewBox={`0 0 480 ${height}`} role="img" aria-label="Map storage in MB, logarithmic scale, 3D references and four 2.5D policies">
      <title>Map storage (logical MB, log scale)</title>
      {#each decades as power}
        <line x1={xFor(10 ** power)} x2={xFor(10 ** power)} y1={PLOT.top - 4} y2={PLOT.top + rows.length * PLOT.row} stroke="var(--line)"/>
        <text class="tick-x" x={xFor(10 ** power)} y={PLOT.top + rows.length * PLOT.row + 14} text-anchor="middle">{decadeLabel(power)}</text>
      {/each}
      {#each rows as row, index}
        {@const y = PLOT.top + index * PLOT.row}
        <text class="bar-label" x={PLOT.left - 8} y={y + 17} text-anchor="end">{row.label}</text>
        {#if row.bytes !== null && row.bytes > 0}
          <rect class="storage-bar" x={PLOT.left} y={y + 6} width={Math.max(2, xFor(mb(row.bytes)) - PLOT.left)} height="16" rx="2" fill={color(row)} fill-opacity={row.kind === 'analytical' ? 0.35 : 0.85} stroke={color(row)} stroke-dasharray={row.kind === 'analytical' ? '4 3' : undefined}><title>{row.label} · {bytes(row, row.bytes)} · {evidence(row)}</title></rect>
        {:else}
          <text class="bar-unavailable" x={PLOT.left + 4} y={y + 17}>unavailable</text>
        {/if}
      {/each}
      <text class="axis-title-x" x={(PLOT.left + PLOT.right) / 2} y={height - 6} text-anchor="middle">Logical map storage (MB, log scale) ↓ · dashed = analytical</text>
    </svg>
  {:else}<div class="plot-unavailable">Storage values are unavailable in the loaded report.</div>{/if}
  <div class="table-wrap"><table>
    <thead><tr><th>Representation</th><th>Evidence</th><th>Logical ↓</th><th>Allocated ↓</th><th>Cells / voxels</th><th>vs sparse 3D</th><th>vs dense 3D</th></tr></thead>
    <tbody>
      {#each rows as row}
        <tr data-storage-row={row.key}><td><strong>{row.label}</strong><br/><span class="baseline-detail">{row.detail}</span></td><td><span class="chip">{evidence(row)}</span></td><td>{bytes(row, row.bytes)}</td><td>{row.key === 'dense_3d' ? (row.kind === 'unavailable' ? 'unavailable' : 'not allocated') : bytes(row, row.allocatedBytes)}</td><td>{count(row.cells)}</td><td>{row.key === 'dense_3d' || row.key === 'sparse_3d' ? '—' : timesSmaller(row.timesSmallerThanSparse)}</td><td>{row.key === 'dense_3d' ? '—' : timesSmaller(row.timesSmallerThanDense)}</td></tr>
      {/each}
    </tbody>
  </table></div>
  <p class="hint">Ratios compare logical bytes on the same input and window. The sparse 3D reference stores occupancy only (no height statistics, class or motion), so it is a lower bound for an equivalent 3D map; its bytes are accounted per measured voxel (16 B logical, 32 B allocated), not malloc-hooked. 2.5D values are each policy's final map. MB = 1,048,576 bytes, as elsewhere in the app. Unavailable values are never shown as zero.</p>
</section>
