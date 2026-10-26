import {describe} from 'node:test';
import assert from 'node:assert/strict';
import benchmark_cache_test from 'node:test';
import {benchmarkCacheInfo, cachedReportLabel} from '../src/renderer/benchmark-report.ts';
import {validateCommand} from '../src/core.ts';
import {readFileSync} from 'node:fs';
import benchmark_quality_test from 'node:test';
import {formatAxisValue, niceAxis, placePointLabels, policyQuality, qualityParetoPolicies, qualityPlotPoints} from '../src/renderer/benchmark-quality.ts';
import benchmark_report_test from 'node:test';
import {acceptBenchmarkReport, benchmarkLifecycle, benchmarkPlan, benchmarkProgressText, benchmarkSequenceFrames, elapsedText, comparisonScope, paretoFrontier, millimetres, percent, qualityResourceRows, referenceBaselines, reportProvenance, semanticQuality, storageComparison, timesSmaller} from '../src/renderer/benchmark-report.ts';
import {after, before, test as comparison_render_test} from 'node:test';
import {createServer, type ViteDevServer} from 'vite';

describe('benchmark cache', () => {
  const hit = {
    type: 'benchmark', state: 'complete', artifact: '/cache/k.json',
    cache: {hit: true, key: 'k', measured_at: '2026-09-30T10:05:09.123+00:00', host: 'bench-host', processor: 'Apple M3', machine: 'arm64'},
  };

  benchmark_cache_test('a cache hit is labelled CACHED with its original measurement time and host', () => {
    const info = benchmarkCacheInfo(hit);
    assert.ok(info);
    assert.equal(info.hit, true);
    assert.equal(cachedReportLabel(info), 'CACHED · measured 2026-09-30 10:05:09 UTC on bench-host (Apple M3)');
  });

  benchmark_cache_test('fresh measurements are never labelled cached', () => {
    assert.equal(benchmarkCacheInfo({type: 'benchmark', state: 'complete', artifact: '/x'}), null);
    const fresh = benchmarkCacheInfo({...hit, cache: {hit: false, stored: true, key: 'k'}});
    assert.equal(fresh, null);
    assert.equal(cachedReportLabel(null), null);
  });

  benchmark_cache_test('missing provenance stays explicit instead of inventing a time or host', () => {
    const info = benchmarkCacheInfo({...hit, cache: {hit: true, key: 'k'}});
    assert.equal(cachedReportLabel(info), 'CACHED · measured at an unrecorded time');
    const hostOnly = benchmarkCacheInfo({...hit, cache: {hit: true, key: 'k', measured_at: 'not a date', processor: 'Apple M3'}});
    assert.equal(cachedReportLabel(hostOnly), 'CACHED · measured not a date on Apple M3');
  });

  benchmark_cache_test('the benchmark command accepts only a boolean force flag', () => {
    assert.deepEqual(validateCommand('benchmark', {count: 5, force: true}).args, {count: 5, force: true});
    assert.throws(() => validateCommand('benchmark', {force: 'yes'}), /force/);
  });
});

describe('benchmark quality', () => {
  const reportFixture = JSON.parse(readFileSync(new URL('./fixtures/benchmark-v2-generic.json', import.meta.url), 'utf8'));

  benchmark_quality_test('surface accuracy and input reconstruction accuracy remain distinct', () => {
    const value = {aggregate: {quality: [{high_resolution_surface_comparison: {
      height_accuracy_10cm: .8, completion_fraction: .9, chamfer_distance_m: .02,
    }, reconstruction: {status: 'available', accuracy: {mean_m: .06}, completion: {mean_m: .08}, chamfer_l1_m: .07}}]}};
    assert.deepEqual(policyQuality(value), {
      heightAccuracy: .8, completion: .9, surfaceChamfer: .02,
      inputAccuracy: .06, inputCompletion: .08, inputChamfer: .07,
    });
  });

  benchmark_quality_test('unavailable, invalid and absent quality measurements never become zero', () => {
    const value = {runs: [{quality: {high_resolution_surface_comparison: {
      height_accuracy_10cm: NaN, completion_fraction: 2, chamfer_distance_m: -1,
    }, reconstruction: {status: 'unavailable', accuracy: {mean_m: 0}}}}]};
    assert.ok(Object.values(policyQuality(value)).every(value => value === null));
    assert.ok(Object.values(policyQuality({})).every(value => value === null));
  });

  benchmark_quality_test('trade-off points use finite measured values, preserve measured zero, and exclude experimental policies', () => {
    const entry = {runs: [{metrics: {memory: {logical_map_bytes: 1048576}}}], aggregate: {
      stage_latency_ns: {map_update: {p50: 5000000}}, quality: [{high_resolution_surface_comparison: {height_accuracy_10cm: 0}}],
    }};
    const report = {policies: {distance_lod: entry, utility_lod_v2: entry, uniform5: {aggregate: {}}}};
    assert.deepEqual(qualityPlotPoints(report, 'memory', 'heightAccuracy'), [{policy: 'distance_lod', x: 1, y: 0}]);
    assert.deepEqual(qualityPlotPoints(report, 'latency', 'heightAccuracy'), [{policy: 'distance_lod', x: 5, y: 0}]);
  });

  benchmark_quality_test('evaluation plots expose measured RSS, active cells, and reconstruction distances', () => {
    const report = JSON.parse(JSON.stringify(reportFixture));
    report.quality_resource.status = 'measured';
    report.quality_resource.same_input_for_all_policies = true;
    report.quality_resource.input_stream_digests = Object.fromEntries(
      ['uniform5', 'uniform40', 'distance_lod', 'utility_lod'].map(policy => [policy, 'same-input']),
    );
    report.quality_resource.policies.forEach((row: any, index: number) => {
      row.rss_bytes = (index + 1) * 1_000_000;
      row.active_cells = (index + 1) * 100;
      report.policies[row.policy].aggregate.quality = [{reconstruction: {
        status: 'available', accuracy: {mean_m: (index + 1) / 100},
        completion: {mean_m: (index + 1) / 80}, chamfer_l1_m: (index + 1) / 90,
      }}];
    });
    assert.equal(qualityPlotPoints(report, 'rss', 'heightAccuracy').length, 4);
    assert.equal(qualityPlotPoints(report, 'activeCells', 'completion').length, 4);
    assert.deepEqual(qualityPlotPoints(report, 'rss', 'inputChamfer').map(point => point.y), [
      1 / 90, 2 / 90, 3 / 90, 4 / 90,
    ]);
    assert.deepEqual(qualityPlotPoints(report, 'rss', 'inputAccuracy').map(point => point.y), [
      .01, .02, .03, .04,
    ]);
  });

  benchmark_quality_test('reconstruction Pareto frontier minimizes resource and distance error only for identical measured input', () => {
    const report = JSON.parse(JSON.stringify(reportFixture));
    report.quality_resource.status = 'measured';
    report.quality_resource.same_input_for_all_policies = true;
    report.quality_resource.input_stream_digests = Object.fromEntries(
      ['uniform5', 'uniform40', 'distance_lod', 'utility_lod'].map(policy => [policy, 'same-input']),
    );
    report.quality_resource.policies.forEach((row: any, index: number) => {
      row.rss_bytes = [40, 30, 20, 25][index] * 1_000_000;
      report.policies[row.policy].aggregate.quality = [{reconstruction: {
        status: 'available', accuracy: {mean_m: [0.01, 0.04, 0.03, 0.02][index]},
      }}];
    });
    assert.deepEqual(qualityParetoPolicies(report, 'rss', 'inputAccuracy'), ['uniform5', 'distance_lod', 'utility_lod']);
    report.quality_resource.same_input_for_all_policies = false;
    assert.deepEqual(qualityParetoPolicies(report, 'rss', 'inputAccuracy'), []);
  });

  benchmark_quality_test('axes use round zero-based ticks that cover the data', () => {
    assert.deepEqual(niceAxis(100), {max: 100, ticks: [0, 25, 50, 75, 100]});
    assert.deepEqual(niceAxis(1_621_047.6), {max: 2_000_000, ticks: [0, 500_000, 1_000_000, 1_500_000, 2_000_000]});
    assert.deepEqual(niceAxis(20.05), {max: 30, ticks: [0, 10, 20, 30]});
    assert.deepEqual(niceAxis(19.9), {max: 20, ticks: [0, 5, 10, 15, 20]});
    assert.deepEqual(niceAxis(953.4), {max: 1000, ticks: [0, 250, 500, 750, 1000]});
    for (const bad of [0, -3, NaN, -Infinity]) assert.deepEqual(niceAxis(bad), {max: 1, ticks: [0, 0.25, 0.5, 0.75, 1]});
    assert.deepEqual([0, 12.5, 250, 40_000, 1_500_000, 0.25].map(formatAxisValue), ['0', '12.5', '250', '40k', '1.5M', '0.3']);
  });

  benchmark_quality_test('point labels never overlap each other or markers and stay inside the plot', () => {
    const box = {left: 66, right: 476, top: 32, bottom: 219};
    // DistanceLOD and UtilityLOD measured ~6 px apart on the active-cells axis.
    const points = [
      {policy: 'uniform5', cx: 406, cy: 50}, {policy: 'uniform40', cx: 79, cy: 120},
      {policy: 'distance_lod', cx: 172.6, cy: 106.9}, {policy: 'utility_lod', cx: 179.1, cy: 107.1},
    ];
    const labels = placePointLabels(points, box);
    assert.deepEqual(labels.map(label => label.text).sort(), ['DistanceLOD', 'Uniform40', 'Uniform5', 'UtilityLOD']);
    const rects = labels.map(label => {
      const width = label.text.length * 6.2;
      const x0 = label.anchor === 'start' ? label.x : label.anchor === 'end' ? label.x - width : label.x - width / 2;
      return {x0, x1: x0 + width, y0: label.y - 10, y1: label.y + 2};
    });
    for (const [index, rect] of rects.entries()) {
      assert.ok(rect.x0 >= box.left && rect.x1 <= box.right && rect.y0 >= box.top && rect.y1 <= box.bottom, labels[index].text);
      for (const other of rects.slice(index + 1)) assert.ok(!(rect.x0 < other.x1 && other.x0 < rect.x1 && rect.y0 < other.y1 && other.y0 < rect.y1), 'labels overlap');
      for (const point of points) assert.ok(!(rect.x0 < point.cx + 6 && point.cx - 6 < rect.x1 && rect.y0 < point.cy + 6 && point.cy - 6 < rect.y1), `${labels[index].text} covers a marker`);
    }
  });
});

describe('benchmark report', () => {
  // Generated by the current benchmarks/run_benchmark.py + C++ binary on a tiny
  // generic dataset (tests/test_desktop_benchmark_contract.py regenerates it).
  const generic = JSON.parse(readFileSync(new URL('./fixtures/benchmark-v2-generic.json', import.meta.url), 'utf8'));
  // Real SemanticPOSS producer output with measured semantic quality.
  const semanticposs = JSON.parse(readFileSync(new URL('../../../reports/external-review/benchmark_run.json', import.meta.url), 'utf8'));
  const clone = (value: unknown) => JSON.parse(JSON.stringify(value));

  benchmark_report_test('canonical generated reports render every public policy from the producer table', () => {
    const accepted = acceptBenchmarkReport(generic, 'generated');
    assert.equal(accepted.complete, true);
    assert.deepEqual(accepted.issues, []);
    const rows = qualityResourceRows(accepted.report);
    assert.deepEqual(rows.map(row => row.policy), ['uniform5', 'uniform40', 'distance_lod', 'utility_lod']);
    for (const row of rows) {
      const producer = generic.quality_resource.policies.find((item: any) => item.policy === row.policy);
      assert.equal(row.source, 'quality_resource');
      assert.equal(row.logicalBytes, producer.logical_map_bytes);
      assert.equal(row.mapP50Ms, producer.map_update_p50_ms);
      assert.equal(row.heightAccuracy10, producer.height_accuracy_10cm);
      assert.equal(row.completion, producer.completion_fraction);
      assert.equal(row.p95Reliable, false, 'four samples cannot support a p95 claim');
    }
    assert.equal(comparisonScope(accepted.report).latencyMetric, 'p50');
  });

  benchmark_report_test('an imported p95 selector cannot override unreliable per-policy sample counts', () => {
    const contradictory = clone(generic);
    contradictory.quality_resource.latency_plot_metric = 'map_update_p95_ms';
    for (const row of contradictory.quality_resource.policies) {
      row.map_update_sample_count = 2;
      row.map_update_p95_reliable = false;
    }
    const rows = qualityResourceRows(contradictory);
    assert.ok(rows.every(row => row.mapSamples === 2 && !row.p95Reliable));
    assert.equal(comparisonScope(contradictory).latencyMetric, 'p50');
  });

  benchmark_report_test('identical input requires all four policy digests to match the producer claim', () => {
    assert.equal(comparisonScope(semanticposs).sameInput, true);

    const different = clone(semanticposs);
    different.quality_resource.input_stream_digests.utility_lod = '0'.repeat(64);
    assert.equal(comparisonScope(different).sameInput, false);

    const incomplete = clone(semanticposs);
    delete incomplete.quality_resource.input_stream_digests.utility_lod;
    assert.equal(comparisonScope(incomplete).sameInput, null);
  });

  benchmark_report_test('semantic mIoU reads semantic_quality.overall.miou as a fraction and flags ground truth', () => {
    const semantic = semanticQuality(acceptBenchmarkReport(semanticposs, 'loaded').report);
    assert.equal(semantic.status, 'measured');
    assert.equal(semantic.miou, semanticposs.semantic_quality.overall.miou);
    assert.equal(percent(semantic.miou), '100%');
    assert.equal(semantic.bins.length, 4);
    assert.deepEqual([semantic.bins[0].minM, semantic.bins[0].maxM], [0, 10]);
    assert.equal(semantic.groundTruth, true);
    const model = clone(semanticposs);
    model.perception.status.semantic = 'cenet';
    model.semantic_quality.overall.miou = 0.4321;
    const neural = semanticQuality(model);
    assert.equal(neural.groundTruth, false);
    assert.equal(percent(neural.miou), '43.2%');
  });

  benchmark_report_test('missing or invalid quality stays unavailable, never zero', () => {
    const semantic = semanticQuality(generic);
    assert.equal(semantic.status, 'unavailable');
    assert.equal(semantic.miou, null);
    assert.match(semantic.reason!, /paired adapter labels/);
    const broken = clone(semanticposs);
    broken.semantic_quality.overall.miou = 1.7;
    assert.equal(semanticQuality(broken).miou, null);
    const partial = clone(generic);
    partial.quality_resource.policies[1] = {policy: 'uniform40', status: 'measured', logical_map_bytes: null, completion_fraction: 'n/a', map_update_p50_ms: 0};
    const row = qualityResourceRows(partial).find(item => item.policy === 'uniform40')!;
    assert.equal(row.logicalBytes, null);
    assert.equal(row.completion, null);
    assert.equal(row.mapP50Ms, 0, 'a measured zero stays zero');
    assert.equal(percent(null), '—');
    assert.equal(millimetres(0.0123), '12.3 mm');
  });

  benchmark_report_test('baselines come from reference_baselines and are labelled analytical/measured/unavailable', () => {
    const rows = referenceBaselines(semanticposs);
    const dense = rows.find(row => row.key === 'uniform_5cm_3d')!;
    assert.equal(dense.kind, 'analytical');
    assert.equal(dense.bytes, semanticposs.reference_baselines.uniform_5cm_3d.estimated_dense_bytes);
    assert.equal(rows.find(row => row.key === 'measured_3d')!.kind, 'unavailable');
    assert.equal(rows.find(row => row.key === 'uniform_5cm_2d')!.cells, 303205);
    const none = referenceBaselines({schema_version: 2, policies: {}});
    assert.equal(none.find(row => row.key === 'uniform_5cm_3d')!.kind, 'unavailable');
  });

  benchmark_report_test('provenance surfaces the recorded commit, tree state and host', () => {
    const provenance = reportProvenance(generic);
    assert.equal(provenance.gitSha, generic.provenance.git_sha);
    assert.equal(typeof provenance.workingTreeDirty, 'boolean');
    assert.equal(provenance.perceptionExecuted, false);
    assert.equal(provenance.frameCount, 4);
    const older = reportProvenance(semanticposs);
    assert.equal(older.workingTreeDirty, semanticposs.provenance.working_tree_dirty);
    const unknown = clone(semanticposs); delete unknown.provenance.working_tree_dirty;
    assert.equal(reportProvenance(unknown).workingTreeDirty, null, 'a missing tree state stays unknown');
    assert.equal(older.processor, 'Intel(R) Core(TM) i5-8350U CPU @ 1.70GHz');
  });

  benchmark_report_test('summary-only and provenance-free reports are accepted but marked incomplete', () => {
    // Shape of the lossy benchmark event the runtime used to send.
    const summary = {schema_version: 2, dataset: 'generic', sequence: 's', policies: Object.fromEntries(
      Object.entries(generic.policies).map(([name, policy]: [string, any]) => [name, {aggregate: policy.aggregate, quality: policy.runs.at(-1).quality}]))};
    const accepted = acceptBenchmarkReport(summary, 'generated');
    assert.equal(accepted.complete, false);
    assert.ok(accepted.issues.some(issue => issue.includes('Provenance is missing')));
    assert.ok(accepted.issues.some(issue => issue.includes('No raw repetitions')));
    const rows = qualityResourceRows(accepted.report);
    assert.ok(rows.every(row => row.source === 'derived'));
    assert.equal(rows[0].mapP50Ms, generic.policies.uniform5.aggregate.stage_latency_ns.map_update.p50 / 1e6);
  });

  benchmark_report_test('legacy desktop exports are migrated narrowly; malformed input is rejected', () => {
    const legacy = {mapping: {schema_version: 2, policies: generic.policies}, provenance: generic.provenance};
    const accepted = acceptBenchmarkReport(legacy, 'loaded');
    assert.equal(accepted.migratedFrom, 'mapping-wrapper');
    assert.equal(accepted.report.provenance.git_sha, generic.provenance.git_sha);
    assert.equal(qualityResourceRows(accepted.report)[0].source, 'derived');
    assert.throws(() => acceptBenchmarkReport(null, 'loaded'), /JSON object/);
    assert.throws(() => acceptBenchmarkReport([], 'loaded'), /JSON object/);
    assert.throws(() => acceptBenchmarkReport({schema_version: 1, policies: {}}, 'loaded'), /schema 1/);
    assert.throws(() => acceptBenchmarkReport({schema_version: 3, policies: {}}, 'loaded'), /schema 3/);
    assert.throws(() => acceptBenchmarkReport({policies: {}}, 'loaded'), /schema null/);
    assert.throws(() => acceptBenchmarkReport({schema_version: 2}, 'loaded'), /no policies/);
  });

  benchmark_report_test('export keeps the complete accepted report, and live and loaded views agree', () => {
    const live = acceptBenchmarkReport(clone(generic), 'generated');
    const exported = JSON.parse(JSON.stringify(live.report));
    const reopened = acceptBenchmarkReport(exported, 'loaded');
    assert.deepEqual(exported, generic);
    assert.deepEqual(qualityResourceRows(reopened.report), qualityResourceRows(live.report));
    assert.deepEqual(reportProvenance(reopened.report), reportProvenance(live.report));
  });

  benchmark_report_test('trade-off points use canonical rows and the reliable latency percentile', () => {
    const memory = qualityPlotPoints(semanticposs, 'memory', 'heightAccuracy');
    assert.equal(memory.length, 4);
    const uniform5 = semanticposs.quality_resource.policies[0];
    assert.deepEqual(memory[0], {policy: 'uniform5', x: uniform5.logical_map_bytes / 1048576, y: uniform5.height_accuracy_10cm});
    const latency = qualityPlotPoints(semanticposs, 'latency', 'completion');
    const expected = semanticposs.quality_resource.latency_plot_metric === 'map_update_p95_ms' ? uniform5.map_update_p95_ms : uniform5.map_update_p50_ms;
    assert.equal(latency[0].x, expected);
  });

  benchmark_report_test('benchmark failure states are normalized for display', () => {
    assert.equal(benchmarkLifecycle('error'), 'failed');
    assert.equal(benchmarkLifecycle('complete'), 'complete');
    assert.equal(benchmarkLifecycle(undefined), 'idle');
  });

  benchmark_report_test('Pareto frontier is only offered for a fully measured, identical-input comparison', () => {
    const frontier = paretoFrontier(semanticposs, 'memory', 'heightAccuracy');
    assert.equal(frontier.available, true);
    assert.deepEqual(frontier.frontier, semanticposs.quality_resource.pareto.memory_vs_height_accuracy.frontier);
    const partial = clone(semanticposs);
    partial.quality_resource.status = 'partial';
    assert.deepEqual(paretoFrontier(partial, 'memory', 'heightAccuracy'), {available: false, frontier: [], reason: 'the comparison is partial'});
    const differing = clone(semanticposs);
    differing.quality_resource.same_input_for_all_policies = false;
    assert.equal(paretoFrontier(differing, 'latency', 'completion').reason, 'policies did not consume identical input');
    const gap = clone(semanticposs);
    gap.quality_resource.pareto.memory_vs_chamfer.unavailable = ['utility_lod'];
    assert.equal(paretoFrontier(gap, 'memory', 'surfaceChamfer').available, false);
    assert.equal(paretoFrontier(generic, 'memory', 'heightAccuracy').available, generic.quality_resource.status === 'measured');
  });

  benchmark_report_test('benchmark selection spans the dataset sequence, not the playback frame limit', () => {
    assert.equal(benchmarkSequenceFrames({frames: 30, sequence_frames: 500}), 500);
    assert.equal(benchmarkSequenceFrames({frames: 30}), 30, 'older runtimes fall back to the session frame count');
    assert.equal(benchmarkSequenceFrames({frames: 0}), null);
    assert.equal(benchmarkSequenceFrames({}), null);
  });

  benchmark_report_test('benchmark defaults give every policy p99-reliable samples when the sequence allows', () => {
    const plan = benchmarkPlan({frames: null, warmup: null, repetitions: null}, 500)!;
    assert.deepEqual([plan.count, plan.warmup, plan.repetitions, plan.measured], [110, 10, 3, 300]);
    assert.equal(plan.p95Reliable, true);
    assert.equal(plan.p99Reliable, true);
    assert.match(plan.hint, /\(110 − 10\) × 3 = 300 measured samples per policy/);
    assert.match(plan.hint, /p95 needs ≥20 and p99 ≥100/);
    const short = benchmarkPlan({frames: null, warmup: null, repetitions: null}, 40)!;
    assert.deepEqual([short.count, short.warmup, short.repetitions], [40, 10, 3], 'frames default to min(110, sequence)');
  });

  benchmark_report_test('benchmark inputs are clamped to what the runtime accepts', () => {
    const clamped = benchmarkPlan({frames: 9999, warmup: 9999, repetitions: 99}, 200)!;
    assert.deepEqual([clamped.count, clamped.warmup, clamped.repetitions], [200, 199, 20], 'frames <= sequence, warm-up < frames, repetitions <= 20');
    const low = benchmarkPlan({frames: 0, warmup: -4, repetitions: 0}, 200)!;
    assert.deepEqual([low.count, low.warmup, low.repetitions], [1, 0, 1]);
    assert.equal(benchmarkPlan({frames: 12.7, warmup: 2.9, repetitions: 1.5}, 200)!.count, 12);
    assert.equal(benchmarkPlan({frames: 10, warmup: null, repetitions: null}, null), null);
  });

  benchmark_report_test('sample-count hint names the gates a small run misses', () => {
    const tiny = benchmarkPlan({frames: 10, warmup: 0, repetitions: 1}, 200)!;
    assert.equal(tiny.measured, 10);
    assert.equal(tiny.p95Reliable, false);
    assert.match(tiny.hint, /p95 and p99 stay descriptive/);
    const mid = benchmarkPlan({frames: 30, warmup: 5, repetitions: 1}, 200)!;
    assert.equal(mid.measured, 25);
    assert.equal(mid.p95Reliable, true);
    assert.equal(mid.p99Reliable, false);
    assert.match(mid.hint, /p99 stays descriptive/);
  });

  benchmark_report_test('running benchmark progress names the policy and repetition', () => {
    const plan = {count: 110, warmup_frames: 10, repetitions: 3, policies: 4};
    assert.equal(benchmarkProgressText({plan}), 'Starting · 110 frames × 3 repetitions × 4 policies');
    assert.match(benchmarkProgressText({plan, progress: {phase: 'staging', frame: 42, frames: 110}}), /staging frames 42\/110/);
    assert.equal(benchmarkProgressText({plan, progress: {phase: 'policy', policy: 'utility_lod', repetition: 2, repetitions: 3, run: 8, runs: 12}}), 'Utility LOD · repetition 2/3 · run 8/12 · 110 frames × 3 repetitions × 4 policies');
    assert.match(benchmarkProgressText({plan, progress: {phase: 'report'}}), /Writing the report/);
    assert.equal(benchmarkLifecycle('cancelled'), 'cancelled');
    assert.equal(elapsedText(0), '0:00');
    assert.equal(elapsedText(125.9), '2:05');
  });

  function withStorage(report: any) {
    const copy = clone(report);
    const logical = (policy: string) => copy.policies[policy].runs.at(-1).metrics.memory.logical_map_bytes;
    copy.reference_baselines.sparse_5cm_3d = {status: 'measured', comparison_basis: 'final_window', final_window: {occupied_voxels: 1000, logical_bytes: 16000, accounted_allocated_bytes: 32000}, cumulative: {occupied_voxels: 1200, logical_bytes: 19200, accounted_allocated_bytes: 38400}};
    copy.reference_baselines.dense_5cm_3d_window = {status: 'analytical_only', window_radius_m: 100.001, dense_voxel_count: 1e9, estimated_dense_bytes: 16e9};
    copy.storage_comparison = {
      schema_version: 1,
      sparse_3d: {evidence: 'measured', occupied_voxels: 1000, logical_bytes: 16000, accounted_allocated_bytes: 32000},
      dense_3d: {evidence: 'analytical', dense_voxel_count: 1e9, estimated_dense_bytes: 16e9},
      policies: Object.fromEntries(['uniform5', 'uniform40', 'distance_lod', 'utility_lod'].map(policy => [policy, {logical_map_bytes: logical(policy), allocated_map_bytes: logical(policy) * 2, active_cells: 10}])),
    };
    return copy;
  }

  benchmark_report_test('storage comparison lists dense 3D, sparse 3D and four 2.5D policies with evidence and ratios', () => {
    const report = withStorage(generic);
    const rows = storageComparison(report);
    assert.deepEqual(rows.map(row => row.key), ['dense_3d', 'sparse_3d', 'uniform5', 'uniform40', 'distance_lod', 'utility_lod']);
    assert.deepEqual(rows.map(row => row.kind), ['analytical', 'measured', 'measured', 'measured', 'measured', 'measured']);
    const dense = rows[0], sparse = rows[1], u5 = rows[2];
    assert.equal(dense.bytes, 16e9);
    assert.equal(dense.cells, 1e9);
    assert.match(dense.detail, /100 m map window/);
    assert.equal(sparse.bytes, 16000);
    assert.equal(sparse.allocatedBytes, 32000);
    assert.equal(sparse.timesSmallerThanDense, 1e6);
    const logical = generic.policies.uniform5.runs.at(-1).metrics.memory.logical_map_bytes;
    assert.equal(u5.bytes, logical);
    assert.equal(u5.allocatedBytes, logical * 2);
    assert.equal(u5.timesSmallerThanSparse, 16000 / logical);
    assert.equal(u5.timesSmallerThanDense, 16e9 / logical);
    const baselines = referenceBaselines(report);
    assert.equal(baselines.find(row => row.key === 'sparse_5cm_3d')!.kind, 'measured');
    assert.equal(baselines.find(row => row.key === 'sparse_5cm_3d')!.bytes, 16000);
  });

  benchmark_report_test('storage values that are missing are unavailable, never zero', () => {
    const report = withStorage(generic);
    report.storage_comparison.sparse_3d.logical_bytes = null;
    report.storage_comparison.dense_3d.estimated_dense_bytes = null;
    report.storage_comparison.policies.uniform40.logical_map_bytes = null;
    delete report.storage_comparison.policies.utility_lod;
    const rows = storageComparison(report);
    const byKey = Object.fromEntries(rows.map(row => [row.key, row]));
    assert.equal(byKey.dense_3d.kind, 'unavailable');
    assert.equal(byKey.dense_3d.bytes, null, 'no fallback to the stream-bounds estimate when the block exists');
    assert.equal(byKey.sparse_3d.kind, 'unavailable');
    assert.equal(byKey.uniform40.kind, 'unavailable');
    assert.equal(byKey.uniform40.bytes, null);
    // A policy absent from the block falls back to its measured quality/resource row.
    assert.equal(byKey.utility_lod.kind, 'measured');
    assert.equal(byKey.utility_lod.bytes, generic.policies.utility_lod.runs.at(-1).metrics.memory.logical_map_bytes);
    assert.equal(byKey.uniform5.timesSmallerThanSparse, null);
    assert.equal(timesSmaller(null), 'unavailable');
    assert.equal(timesSmaller(12.34), '12.3× smaller');
    assert.equal(timesSmaller(0.5), '2× larger');
    assert.equal(timesSmaller(123456), `${(123456).toLocaleString()}× smaller`);
  });

  benchmark_report_test('reports without storage_comparison fall back to the analytical stream-bounds grid', () => {
    const rows = storageComparison(semanticposs);
    assert.equal(rows[0].kind, 'analytical');
    assert.equal(rows[0].bytes, semanticposs.reference_baselines.uniform_5cm_3d.estimated_dense_bytes);
    assert.match(rows[0].detail, /stream XYZ bounds/);
    assert.equal(rows[1].kind, 'unavailable');
    assert.equal(rows[1].bytes, null);
    for (const row of rows.slice(2)) {
      assert.equal(row.kind, 'measured', row.key);
      assert.ok(row.timesSmallerThanDense! > 1, row.key);
      assert.equal(row.timesSmallerThanSparse, null, row.key);
    }
    const empty = storageComparison({schema_version: 2, policies: {}});
    assert.ok(empty.every(row => row.kind === 'unavailable' && row.bytes === null));
  });
});

describe('comparison render', () => {
  // Server-renders the real Evaluation components through Vite + Svelte with
  // real producer reports, so the comparison's visible text is under test.





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

  comparison_render_test('the comparison shows all four policies with shared input identity and directions', async () => {
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

  comparison_render_test('an incomplete comparison says so and draws no frontier', async () => {
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

  comparison_render_test('the overview comparison uses the same four canonical rows', async () => {
    const body = await html('Dashboard', {status: {state: 'paused', frames: 10, index: 0, dataset: 'semanticposs', sequence: '00'}, telemetry: {}, frame: null, report: semanticposs, events: [], openDataset() {}, openPerformance() {}, openMap() {}, openBenchmarks() {}});
    assert.ok(body.includes('Logical map memory ↓'));
    assert.match(body, /Map update p(50|95) ↓/);
    for (const label of ['Uniform5', 'Uniform40', 'DistanceLOD', 'UtilityLOD']) assert.ok(body.includes(`${label} · `), label);
    assert.ok(body.includes('identical input for all four policies'));
  });

  comparison_render_test('trade-off plots label every policy directly and use round, compact axis ticks', async () => {
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

  comparison_render_test('the storage section renders dense 3D, sparse 3D and four 2.5D rows with badges and ratios', async () => {
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

  comparison_render_test('the storage section says unavailable rather than zero for missing values', async () => {
    const body = await html('StorageComparison', {report: {schema_version: 2, policies: {}}});
    assert.ok(body.includes('Storage values are unavailable in the loaded report.'));
    assert.ok(body.includes('unavailable'));
    assert.ok(!/<td>0 MB<\/td>/.test(body));
    const legacy = await html('StorageComparison', {report: semanticposs});
    assert.match(legacy, /data-storage-row="sparse_3d"><td><strong>Sparse 5 cm 3D voxel hash<\/strong>.*?UNAVAILABLE/s);
    assert.equal((legacy.match(/class="storage-bar"/g) ?? []).length, 5);
  });
});
