import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, mkdirSync, copyFileSync, writeFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import test from 'node:test';

test('launches the Tauri JS entrypoint without an npm shell shim, preserving arguments and cwd', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'veyra cli with spaces '));
  try {
    mkdirSync(path.join(root, 'tools'));
    const cli = path.join(root, 'apps', 'desktop', 'node_modules', '@tauri-apps', 'cli');
    mkdirSync(cli, {recursive: true});
    copyFileSync(new URL('./tauri.mjs', import.meta.url), path.join(root, 'tools', 'tauri.mjs'));
    writeFileSync(path.join(cli, 'tauri.js'), 'console.log(JSON.stringify({args:process.argv.slice(2),cwd:process.cwd()})); process.exit(Number(process.env.CLI_EXIT || 0));');
    const args = ['build', '--config', 'config with spaces.json', '--bundles', 'deb,rpm', 'literal;&value'];
    const result = spawnSync(process.execPath, [path.join(root, 'tools', 'tauri.mjs'), ...args], {encoding:'utf8', cwd:tmpdir()});
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout), {args, cwd:root});
    const failed = spawnSync(process.execPath, [path.join(root, 'tools', 'tauri.mjs'), '--version'], {encoding:'utf8', env:{...process.env, CLI_EXIT:'7'}});
    assert.equal(failed.status, 7, failed.stderr);
  } finally {
    rmSync(root, {recursive:true, force:true});
  }
});
