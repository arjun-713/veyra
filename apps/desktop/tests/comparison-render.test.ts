// Server-renders the real Evaluation components through Vite + Svelte with
// real producer reports, so the comparison's visible text is under test.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {after, before, test} from 'node:test';
import {createServer, type ViteDevServer} from 'vite';

const root = new URL('..', import.meta.url).pathname;
const generic = JSON.parse(readFileSync(new URL('./fixtures/benchmark-v2-generic.json', import.meta.url), 'utf8'));
const semanticposs = JSON.parse(readFileSync(new URL('../../../reports/external-review/benchmark_run.json', import.meta.url), 'utf8'));
const meta = {origin: 'loaded', complete: true, issues: [], migratedFrom: null};
let server: ViteDevServer;
let html: (component: string, props: Record<string, unknown>) => Promise<string>;

before(async () => {
  server = await createServer({configFile: `${root}vite.renderer.config.ts`, root, server: {middlewareMode: true, hmr: false}, appType: 'custom', logLevel: 'error'});
  const {render} = await server.ssrLoadModule('svelte/server');
  html = async (component, props) => {
    const module = await server.ssrLoadModule(`/src/renderer/${component}.svelte`);
    return render(module.default, {props}).body.replace(/<!--[^>]*-->/g, '');
  };
});
after(async () => { await server?.close(); });

test('the comparison shows all four policies with shared input identity and directions', async () => {
  const body = await html('ComparisonEvidence', {report: semanticposs, meta});
  for (const label of ['Uniform5', 'Uniform40', 'DistanceLOD', 'UtilityLOD']) assert.ok(body.includes(`<strong>${label}</strong>`), label);
  assert.match(body, /semanticposs · 00 · 10 frames · identical input · stream [0-9a-f]{12}/);
  assert.ok(body.includes('Logical map ↓') && body.includes('Height accuracy ≤10 cm ↑') && body.includes('Critical retention ↑'));
  assert.ok(body.includes('— not measured in this report (never zero)'));
  assert.ok(body.includes('Ringed points are non-dominated'));
  for (const label of ['Map quality vs measured RSS', 'Map quality vs mapper latency', 'Reconstruction Chamfer vs RSS', 'Map quality vs active cells']) {
    assert.ok(body.includes(label), label);
  }
  assert.ok(body.includes('Reconstruction accuracy distance') && body.includes('Reconstruction completion distance'));
  assert.ok(body.includes('DATASET GROUND TRUTH'), 'ground-truth mIoU is labelled');
  assert.ok(body.includes('ANALYTICAL') && body.includes('est. '), 'dense 3D is an analytical estimate');
  assert.match(body, /Measured sparse 3D baseline<\/strong><\/td><td><span class="chip">UNAVAILABLE/);
  assert.ok(body.includes('Storage: 3D vs 2.5D'));
  assert.match(body, /Commit<\/span><b[^>]*>9f457a20c769/);
});

test('an incomplete comparison says so and draws no frontier', async () => {
  const partial = JSON.parse(JSON.stringify(generic));
  partial.quality_resource.status = 'partial';
  partial.quality_resource.same_input_for_all_policies = false;
  const body = await html('ComparisonEvidence', {report: partial, meta: {...meta, complete: false, issues: ['Provenance is missing: commit, host and input identity are unavailable.']}});
  assert.ok(body.includes('INPUTS DIFFER — not comparable'));
  assert.ok(body.includes('not a like-for-like comparison'));
  assert.ok(body.includes('PARTIAL / UNVERIFIED') && body.includes('no Pareto claim'));
  assert.ok(!body.includes('Ringed points are non-dominated'));
  assert.ok(body.includes('INCOMPLETE') && body.includes('Provenance is missing'));
  assert.ok(body.includes('Semantic quality<span>UNAVAILABLE'), 'generic reports have no semantic evaluation');
});

test('the overview comparison uses the same four canonical rows', async () => {
  const body = await html('Dashboard', {status: {state: 'paused', frames: 10, index: 0, dataset: 'semanticposs', sequence: '00'}, telemetry: {}, frame: null, report: semanticposs, events: [], openDataset() {}, openPerformance() {}, openMap() {}, openBenchmarks() {}});
  assert.ok(body.includes('Logical map memory ↓'));
  assert.match(body, /Map update p(50|95) ↓/);
  for (const label of ['Uniform5', 'Uniform40', 'DistanceLOD', 'UtilityLOD']) assert.ok(body.includes(`${label} · `), label);
  assert.ok(body.includes('identical input for all four policies'));
});

test('trade-off plots label every policy directly and use round, compact axis ticks', async () => {
  const body = await html('QualityTradeoff', {report: semanticposs});
  const svgs = body.match(/<svg[\s\S]*?<\/svg>/g) ?? [];
  // This older fixture predates input reconstruction, so that plot is unavailable.
  assert.equal(svgs.length, 3);
  assert.ok(!/NaN|undefined|Infinity/.test(body));
  for (const svg of svgs) {
    const labels = [...svg.matchAll(/class="point-label"[^>]*>([^<]*)</g)].map(match => match[1]).sort();
    assert.deepEqual(labels, ['DistanceLOD', 'Uniform40', 'Uniform5', 'UtilityLOD']);
    const ticks = [...svg.matchAll(/class="tick-[xy]"[^>]*>([^<]*)</g)].map(match => match[1]);
    for (const tick of ticks) assert.match(tick, /^\d+(\.\d)?[kM]?$/, `compact locale-free tick ${tick}`);
  }
  assert.ok(body.includes('Map-update p50 (ms) ↓</text>') || body.includes('Map-update p95 (ms) ↓</text>'), 'latency axis ends with its direction');
  assert.ok(body.includes('Peak RSS memory (MB) ↓') && body.includes('Active map cells ↓'));
});

test('the storage section renders dense 3D, sparse 3D and four 2.5D rows with badges and ratios', async () => {
  const report = JSON.parse(JSON.stringify(generic));
  const logical = (policy: string) => report.policies[policy].runs.at(-1).metrics.memory.logical_map_bytes;
  report.storage_comparison = {
    sparse_3d: {occupied_voxels: 100000, logical_bytes: 1600000, accounted_allocated_bytes: 3200000},
    dense_3d: {dense_voxel_count: 1e9, estimated_dense_bytes: 16e9},
    policies: Object.fromEntries(['uniform5', 'uniform40', 'distance_lod', 'utility_lod'].map(policy => [policy, {logical_map_bytes: logical(policy), allocated_map_bytes: logical(policy), active_cells: 7}])),
  };
  const body = await html('ComparisonEvidence', {report, meta});
  assert.ok(body.includes('Storage: 3D vs 2.5D'));
  for (const key of ['dense_3d', 'sparse_3d', 'uniform5', 'uniform40', 'distance_lod', 'utility_lod']) assert.ok(body.includes(`data-storage-row="${key}"`), key);
  assert.equal((body.match(/class="storage-bar"/g) ?? []).length, 6, 'six bars');
  const denseMb = (16e9 / 1048576).toLocaleString(undefined, {maximumFractionDigits: 1});
  assert.ok(new RegExp(`Dense 5 cm 3D grid</strong>.*?<span class="chip">ANALYTICAL</span></td><td>est\\. ${denseMb.replace(/[.]/g, '\\.')} MB`, 's').test(body));
  assert.match(body, /Sparse 5 cm 3D voxel hash<\/strong>.*?MEASURED COUNT/s);
  assert.ok(body.includes('× smaller'));
  assert.ok(body.includes('log scale') && body.includes('dashed = analytical'));
  assert.ok(!/NaN|Infinity/.test(body));
});

test('the storage section says unavailable rather than zero for missing values', async () => {
  const body = await html('StorageComparison', {report: {schema_version: 2, policies: {}}});
  assert.ok(body.includes('Storage values are unavailable in the loaded report.'));
  assert.ok(body.includes('unavailable'));
  assert.ok(!/<td>0 MB<\/td>/.test(body));
  const legacy = await html('StorageComparison', {report: semanticposs});
  assert.match(legacy, /data-storage-row="sparse_3d"><td><strong>Sparse 5 cm 3D voxel hash<\/strong>.*?UNAVAILABLE/s);
  assert.equal((legacy.match(/class="storage-bar"/g) ?? []).length, 5);
});
