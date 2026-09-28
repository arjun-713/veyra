import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {policyQuality, qualityParetoPolicies, qualityPlotPoints} from '../src/renderer/benchmark-quality.ts';

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
