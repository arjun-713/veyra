<script lang="ts">
 import {anatomyRange, type CellAnatomy} from './cell-anatomy';
 let {anatomy} = $props<{anatomy: CellAnatomy}>();
 const W = 132, H = 168, PAD = 10;
 const range = $derived(anatomyRange(anatomy));
 function yOf(z: number | null): number | null {
  if (z === null || !range) return null;
  const t = (z - range.lo) / Math.max(range.hi - range.lo, 1e-9);
  return H - PAD - t * (H - 2 * PAD);
 }
 const fmt = (v: number | null, digits = 2) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '—');
</script>

<div class="anatomy" aria-label="2.5D cell vertical anatomy">
 <div class="panel-heading">2.5D ANATOMY <span>MEASURED</span></div>
 {#if !anatomy.available}
  <p class="hint">{anatomy.notes[0]}</p>
 {:else if !range}
  <p class="hint">No measurable heights in any layer — nothing to draw, nothing cleared.</p>
 {:else}
  <div class="anatomy-body">
   <svg width={W} height={H} role="img" aria-label="Ground, obstacle and overhead evidence by height">
    {#each anatomy.layers as l, i}
     {@const top = yOf(l.max) ?? yOf(l.mean)}
     {@const bottom = yOf(l.min) ?? yOf(l.mean)}
     {@const mid = yOf(l.mean)}
     {#if l.state === 'present' && top !== null && bottom !== null}
      {#if l.name === 'ground'}
       <line x1={PAD} x2={W - PAD} y1={mid} y2={mid} stroke="#33d980" stroke-width="3"/>
       {#if top !== bottom}<line x1={PAD + 14} x2={W - PAD - 14} y1={top} y2={top} stroke="#33d980" stroke-width="1" opacity="0.6"/><line x1={PAD + 14} x2={W - PAD - 14} y1={bottom} y2={bottom} stroke="#33d980" stroke-width="1" opacity="0.6"/>{/if}
      {:else if l.name === 'obstacle'}
       <rect x={PAD + 22} width={W - 2 * (PAD + 22)} y={top} height={Math.max(bottom - top, 3)} fill="#ffb340" opacity="0.75"/>
      {:else}
       <rect x={PAD + 8} width={W - 2 * (PAD + 8)} y={top} height={Math.max(bottom - top, 3)} fill="none" stroke="#d966d9" stroke-width="1.5" stroke-dasharray="4 2"/>
       {#if mid !== null}<line x1={PAD + 8} x2={W - PAD - 8} y1={mid} y2={mid} stroke="#d966d9" stroke-width="1.5"/>{/if}
      {/if}
     {:else}
      <text x={W / 2} y={34 + i * 52} text-anchor="middle" fill="#59616b" font-size="9">{l.name} · no evidence</text>
      <line x1={PAD + 8} x2={W - PAD - 8} y1={42 + i * 52} y2={42 + i * 52} stroke="#59616b" stroke-width="1" stroke-dasharray="3 3" opacity="0.6"/>
     {/if}
    {/each}
    <text x={4} y={PAD + 2} fill="#8a94a6" font-size="8">↑ z</text>
    <text x={4} y={PAD + 2} fill="none" font-size="8">.</text>
   </svg>
   <div class="anatomy-numbers">
    {#each anatomy.layers as l}
     <div class:empty={l.state === 'empty'}>
      <span>{l.name}</span>
      {#if l.state === 'present'}
       <b>n={l.count} · mean {fmt(l.mean)} m</b>
       <small>min {fmt(l.min)} · max {fmt(l.max)} m</small>
      {:else}<b>Unavailable</b>{/if}
     </div>
    {/each}
    <div><span>pooled z</span><b>{fmt(anatomy.pooled.mean)} m</b><small>min {fmt(anatomy.pooled.zmin)} · max {fmt(anatomy.pooled.zmax)} m · var {fmt(anatomy.pooled.variance, 4)} m² · n={anatomy.pooled.count ?? '—'}</small></div>
   </div>
  </div>
 {/if}
 {#if anatomy.resolution || anatomy.lod !== null}<p class="hint">Cell {anatomy.resolution ?? '—'}{anatomy.lod !== null ? ` · L${anatomy.lod}` : ''} — XY location plus vertical statistics, not a voxel volume.</p>{/if}
 {#each anatomy.notes as note}<p class="hint anatomy-note">{note}</p>{/each}
</div>

<style>
 .anatomy-body{display:flex;gap:10px;align-items:flex-start}
 .anatomy-numbers{flex:1;min-width:0}
 .anatomy-numbers>div{margin-bottom:8px}
 .anatomy-numbers span{display:block;font-size:9px;color:var(--secondary);text-transform:capitalize}
 .anatomy-numbers b{display:block;font-size:11px;font-variant-numeric:tabular-nums}
 .anatomy-numbers small{display:block;font-size:10px;color:var(--secondary)}
 .anatomy-numbers .empty b{color:var(--secondary);font-weight:400}
 .anatomy-note{color:var(--secondary)}
 svg{background:#0b1219;border-radius:6px}
</style>
