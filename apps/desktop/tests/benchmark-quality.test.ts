import assert from 'node:assert/strict';
import test from 'node:test';
import {policyQuality, qualityPlotPoints} from '../src/renderer/benchmark-quality.ts';

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
