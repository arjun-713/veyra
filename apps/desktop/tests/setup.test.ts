import assert from 'node:assert/strict';
import test from 'node:test';
import {errorRecovery, previewReadiness, runtimeLabel, sessionActive} from '../src/renderer/setup.ts';
import {profileConfig} from '../src/renderer/dashboard.ts';

const catalog = {root: '/datasets/poss', sequences: [{id: '00', frames: 488}, {id: '01', frames: 0}]};

test('preview requires a discovered, non-empty selected sequence', () => {
  assert.equal(previewReadiness(null, '', false).ready, false);
  assert.equal(previewReadiness(catalog, 'missing', false).ready, false);
  assert.equal(previewReadiness(catalog, '01', false).ready, false);
  assert.equal(previewReadiness(catalog, '00', false).ready, true);
  assert.equal(previewReadiness(catalog, '00', true).ready, false);
  assert.equal(previewReadiness({...catalog, root: ''}, '00', false).ready, false);
});

test('session actions follow runtime truth even if a stopped status retains dataset metadata', () => {
  assert.equal(sessionActive({state: 'stopped', dataset: 'semanticposs', frames: 488}), false);
  assert.equal(sessionActive({state: 'error', dataset: 'semanticposs'}), false);
  assert.equal(sessionActive({state: 'running', dataset: 'semanticposs'}), true);
  assert.equal(sessionActive({state: 'paused', dataset: 'semanticposs'}), true);
});

test('runtime states have plain user labels and preserve unknown backend states', () => {
  assert.equal(runtimeLabel('unconfigured'), 'No session');
  assert.equal(runtimeLabel('running'), 'Playing');
  assert.equal(runtimeLabel('paused'), 'Paused');
  assert.equal(runtimeLabel('stopped'), 'Stopped');
  assert.equal(runtimeLabel('recovering'), 'recovering');
});

test('changing the display profile preserves the selected resolution policy', () => {
  for (const name of ['LowResource', 'Performance', 'Balanced', 'Quality']) {
    assert.equal(profileConfig({map: {policy: 'utility_lod'}}, name).map.policy, 'utility_lod');
  }
});

test('invalid configuration and missing dependencies do not suggest blind restart', () => {
  assert.equal(errorRecovery('SyntaxError: Unexpected token in JSON').restart, false);
  const missing = errorRecovery("runtime exited: exit status: 1: ModuleNotFoundError: No module named numpy");
  assert.equal(missing.restart, false);
  assert.match(missing.action, /Python|backend/);
  assert.equal(errorRecovery('MODEL_NOT_FOUND: checkpoint missing').restart, false);
  assert.equal(errorRecovery('PROTOCOL_VERSION_MISMATCH').restart, false);
});

test('unexpected process exit keeps a real recovery path without claiming success', () => {
  const advice = errorRecovery('CONTROLLER_ERROR: runtime process error: runtime exited: exit status: 1');
  assert.equal(advice.restart, true);
  assert.match(advice.action, /Diagnostics/);
  assert.match(advice.title, /stopped/);
});

test('unknown errors remain errors and recommend evidence, not a fabricated diagnosis', () => {
  const advice = errorRecovery('Something unexpected happened');
  assert.equal(advice.restart, false);
  assert.match(advice.action, /Diagnostics/);
  assert.match(errorRecovery('WEBGL_UNAVAILABLE').action, /WebGL/);
});
