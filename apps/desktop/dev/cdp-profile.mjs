// Development-only renderer profiler: launches headless Chrome, opens the
// replay harness (replay.html) and records frame pacing, long tasks, CDP
// performance metrics and a sampled CPU profile for each workspace.
// Usage: node dev/cdp-profile.mjs [url] [seconds-per-view] [out.json]
import {spawn} from 'node:child_process';
import {mkdtempSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const url = process.argv[2] ?? 'http://127.0.0.1:1420/replay.html';
const seconds = Number(process.argv[3] ?? 8);
const output = process.argv[4];
const chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const port = 9333;
const browser = spawn(chrome, [
  '--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), 'veyra-cdp-'))}`,
  '--window-size=1600,1000', '--no-first-run', '--enable-gpu', '--ignore-gpu-blocklist', 'about:blank',
], {stdio: 'ignore'});
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let target;
for (let attempt = 0; attempt < 50 && !target; attempt++) {
  await sleep(200);
  try { target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(item => item.type === 'page'); } catch {}
}
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(resolve => socket.addEventListener('open', resolve));
let id = 0; const pending = new Map();
socket.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) { pending.get(message.id)(message); pending.delete(message.id); }
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const key = ++id; pending.set(key, message => message.error ? reject(new Error(`${method}: ${message.error.message}`)) : resolve(message.result));
  socket.send(JSON.stringify({id: key, method, params}));
});
const evaluate = async expression => (await send('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true})).result.value;

await send('Page.enable'); await send('Runtime.enable'); await send('Performance.enable'); await send('Profiler.enable');
await send('Page.navigate', {url});
for (let attempt = 0; attempt < 100; attempt++) { await sleep(200); if (await evaluate('!!window.__replay && !!document.querySelector("nav")')) break; }
await evaluate(`window.__samples = {frames: [], longTasks: []};
  new PerformanceObserver(list => { for (const entry of list.getEntries()) window.__samples.longTasks.push(entry.duration); }).observe({entryTypes: ['longtask']});
  (function tick(now) { window.__samples.frames.push(now); requestAnimationFrame(tick); })(performance.now());`);

async function measure(name, action) {
  if (action) await evaluate(action);
  await sleep(1500);
  await evaluate('window.__samples.frames = []; window.__samples.longTasks = []; window.__renderedFrames = 0;');
  const before = Object.fromEntries((await send('Performance.getMetrics')).metrics.map(m => [m.name, m.value]));
  await send('Profiler.setSamplingInterval', {interval: 500});
  await send('Profiler.start');
  await sleep(seconds * 1000);
  const {profile} = await send('Profiler.stop');
  const after = Object.fromEntries((await send('Performance.getMetrics')).metrics.map(m => [m.name, m.value]));
  const samples = await evaluate('window.__samples');
  const gaps = samples.frames.slice(1).map((t, i) => t - samples.frames[i]).sort((a, b) => a - b);
  const q = p => gaps.length ? +gaps[Math.min(gaps.length - 1, Math.floor(p * gaps.length))].toFixed(1) : null;
  const self = new Map();
  const byId = new Map(profile.nodes.map(node => [node.id, node]));
  const interval = (profile.endTime - profile.startTime) / Math.max(1, profile.samples.length) / 1000;
  for (const sample of profile.samples) {
    const frame = byId.get(sample).callFrame;
    const key = `${frame.functionName || '(anonymous)'} ${frame.url.split('/').pop()}:${frame.lineNumber + 1}`;
    self.set(key, (self.get(key) ?? 0) + interval);
  }
  const top = [...self].filter(([key]) => !key.startsWith('(idle)') && !key.startsWith('(program)'))
    .sort((a, b) => b[1] - a[1]).slice(0, 12).map(([key, ms]) => ({fn: key, self_ms_per_s: +(ms / seconds).toFixed(1)}));
  const d = key => +((after[key] - before[key]) / seconds * 1000).toFixed(1);
  const result = {
    view: name, rafs_per_s: +(samples.frames.length / seconds).toFixed(1),
    frame_ms_p50: q(0.5), frame_ms_p95: q(0.95), frame_ms_p99: q(0.99),
    long_tasks: samples.longTasks.length, long_task_ms_total: +samples.longTasks.reduce((s, v) => s + v, 0).toFixed(0),
    main_thread_ms_per_s: {task: d('TaskDuration'), script: d('ScriptDuration'), layout: d('LayoutDuration'), recalc_style: d('RecalcStyleDuration')},
    js_heap_mb: +(after.JSHeapUsedSize / 1048576).toFixed(1), dom_nodes: after.Nodes, top_self_time: top,
  };
  console.log(JSON.stringify(result, null, 1));
  return result;
}

const click = label => `[...document.querySelectorAll('nav button')].find(b => b.textContent.trim() === '${label}')?.click()`;
const results = [];
results.push(await measure('overview (3 canvases)', click('Overview')));
results.push(await measure('viewer (map canvas)', click('Viewer')));
results.push(await measure('performance charts', click('Performance')));
results.push(await measure('idle viewer, playback paused', `${click('Viewer')}; window.veyra.command('pause')`));
if (output) writeFileSync(output, JSON.stringify(results, null, 1));
socket.close(); browser.kill();
