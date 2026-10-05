import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {formatAxisValue, niceAxis, placePointLabels, policyQuality, qualityParetoPolicies, qualityPlotPoints} from '../src/renderer/benchmark-quality.ts';

const reportFixture = JSON.parse(readFileSync(new URL('./fixtures/benchmark-v2-generic.json', import.meta.url), 'utf8'));

test('surface accuracy and input reconstruction accuracy remain distinct', () => {
  const value = {aggregate: {quality: [{high_resolution_surface_comparison: {
    height_accuracy_10cm: .8, completion_fraction: .9, chamfer_distance_m: .02,
  }, reconstruction: {status: 'available', accuracy: {mean_m: .06}, completion: {mean_m: .08}, chamfer_l1_m: .07}}]}};
  assert.deepEqual(policyQuality(value), {
    heightAccuracy: .8, completion: .9, surfaceChamfer: .02,
    inputAccuracy: .06, inputCompletion: .08, inputChamfer: .07,
  });
});

test('unavailable, invalid and absent quality measurements never become zero', () => {
  const value = {runs: [{quality: {high_resolution_surface_comparison: {
    height_accuracy_10cm: NaN, completion_fraction: 2, chamfer_distance_m: -1,
  }, reconstruction: {status: 'unavailable', accuracy: {mean_m: 0}}}}]};
  assert.ok(Object.values(policyQuality(value)).every(value => value === null));
  assert.ok(Object.values(policyQuality({})).every(value => value === null));
});

test('trade-off points use finite measured values, preserve measured zero, and exclude experimental policies', () => {
  const entry = {runs: [{metrics: {memory: {logical_map_bytes: 1048576}}}], aggregate: {
    stage_latency_ns: {map_update: {p50: 5000000}}, quality: [{high_resolution_surface_comparison: {height_accuracy_10cm: 0}}],
  }};
  const report = {policies: {distance_lod: entry, utility_lod_v2: entry, uniform5: {aggregate: {}}}};
  assert.deepEqual(qualityPlotPoints(report, 'memory', 'heightAccuracy'), [{policy: 'distance_lod', x: 1, y: 0}]);
  assert.deepEqual(qualityPlotPoints(report, 'latency', 'heightAccuracy'), [{policy: 'distance_lod', x: 5, y: 0}]);
});

test('evaluation plots expose measured RSS, active cells, and reconstruction distances', () => {
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

test('reconstruction Pareto frontier minimizes resource and distance error only for identical measured input', () => {
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

test('axes use round zero-based ticks that cover the data', () => {
  assert.deepEqual(niceAxis(100), {max: 100, ticks: [0, 25, 50, 75, 100]});
  assert.deepEqual(niceAxis(1_621_047.6), {max: 2_000_000, ticks: [0, 500_000, 1_000_000, 1_500_000, 2_000_000]});
  assert.deepEqual(niceAxis(20.05), {max: 30, ticks: [0, 10, 20, 30]});
  assert.deepEqual(niceAxis(19.9), {max: 20, ticks: [0, 5, 10, 15, 20]});
  assert.deepEqual(niceAxis(953.4), {max: 1000, ticks: [0, 250, 500, 750, 1000]});
  for (const bad of [0, -3, NaN, -Infinity]) assert.deepEqual(niceAxis(bad), {max: 1, ticks: [0, 0.25, 0.5, 0.75, 1]});
  assert.deepEqual([0, 12.5, 250, 40_000, 1_500_000, 0.25].map(formatAxisValue), ['0', '12.5', '250', '40k', '1.5M', '0.3']);
});

test('point labels never overlap each other or markers and stay inside the plot', () => {
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
