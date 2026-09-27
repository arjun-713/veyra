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
  assert.ok(body.includes('Ringed: Pareto-optimal'));
  assert.ok(body.includes('DATASET GROUND TRUTH'), 'ground-truth mIoU is labelled');
  assert.ok(body.includes('ANALYTICAL') && body.includes('est. '), 'dense 3D is an analytical estimate');
  assert.match(body, /Measured sparse 3D baseline<\/strong><\/td><td><span class="chip">UNAVAILABLE/);
  assert.match(body, /Commit<\/span><b[^>]*>9f457a20c769/);
});

test('an incomplete comparison says so and draws no frontier', async () => {
  const partial = JSON.parse(JSON.stringify(generic));
  partial.quality_resource.status = 'partial';
  partial.quality_resource.same_input_for_all_policies = false;
  const body = await html('ComparisonEvidence', {report: partial, meta: {...meta, complete: false, issues: ['Provenance is missing: commit, host and input identity are unavailable.']}});
  assert.ok(body.includes('INPUTS DIFFER — not comparable'));
  assert.ok(body.includes('not a like-for-like comparison'));
  assert.ok(body.includes('No frontier drawn'));
  assert.ok(!body.includes('Ringed: Pareto-optimal'));
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
