import assert from 'node:assert/strict';
import test from 'node:test';
import {benchmarkCacheInfo, cachedReportLabel} from '../src/renderer/benchmark-report.ts';
import {validateCommand} from '../src/core.ts';

const hit = {
  type: 'benchmark', state: 'complete', artifact: '/cache/k.json',
  cache: {hit: true, key: 'k', measured_at: '2026-09-30T10:05:09.123+00:00', host: 'bench-host', processor: 'Apple M3', machine: 'arm64'},
};

test('a cache hit is labelled CACHED with its original measurement time and host', () => {
  const info = benchmarkCacheInfo(hit);
  assert.ok(info);
  assert.equal(info.hit, true);
  assert.equal(cachedReportLabel(info), 'CACHED · measured 2026-09-30 10:05:09 UTC on bench-host (Apple M3)');
});

test('fresh measurements are never labelled cached', () => {
  assert.equal(benchmarkCacheInfo({type: 'benchmark', state: 'complete', artifact: '/x'}), null);
  const fresh = benchmarkCacheInfo({...hit, cache: {hit: false, stored: true, key: 'k'}});
  assert.equal(fresh, null);
  assert.equal(cachedReportLabel(null), null);
});

test('missing provenance stays explicit instead of inventing a time or host', () => {
  const info = benchmarkCacheInfo({...hit, cache: {hit: true, key: 'k'}});
  assert.equal(cachedReportLabel(info), 'CACHED · measured at an unrecorded time');
  const hostOnly = benchmarkCacheInfo({...hit, cache: {hit: true, key: 'k', measured_at: 'not a date', processor: 'Apple M3'}});
  assert.equal(cachedReportLabel(hostOnly), 'CACHED · measured not a date on Apple M3');
});

test('the benchmark command accepts only a boolean force flag', () => {
  assert.deepEqual(validateCommand('benchmark', {count: 5, force: true}).args, {count: 5, force: true});
  assert.throws(() => validateCommand('benchmark', {force: 'yes'}), /force/);
});
