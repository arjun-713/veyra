// Development-only renderer harness: replays recorded runtime visualization
// frames (apps/desktop/dev/frames, produced by the real Python runtime) into
// the unmodified App so the renderer can be profiled in a normal browser.
// Never part of the Tauri build (vite builds index.html only).
import type {DesktopAPI} from '../api';
import type {Json, WireFrame} from '../core';

const FRAMES = '/dev/frames';
type Listener<T> = (value: T) => void;
const events = new Set<Listener<Json>>();
const visuals = new Set<Listener<WireFrame>>();
const params = new URLSearchParams(location.search);
const fps = Number(params.get('fps') ?? 10);
let status: Json = {state: 'paused', index: 0, frames: 0, dataset: 'generic', sequence: '011', policy: 'distance_lod', speed: 1, layer: 'semantic'};
let frames: WireFrame[] = [];
let timer: ReturnType<typeof setInterval> | undefined;
let generation = 0;

async function load() {
  const index = await (await fetch(`${FRAMES}/index.json`)).json();
  frames = await Promise.all(index.frames.map(async (name: string) => {
    const [metadata, payload] = await Promise.all([
      fetch(`${FRAMES}/${name}.json`).then(response => response.json()),
      fetch(`${FRAMES}/${name}.bin`).then(response => response.arrayBuffer()),
    ]);
    return {metadata, payload: new Uint8Array(payload)} as WireFrame;
  }));
  status = {...status, frames: frames.length};
  (window as any).__replay = {frames: frames.length, telemetry: index.telemetry};
}

function emit(index: number) {
  const frame = frames[index % frames.length];
  status = {...status, index: index % frames.length};
  const metadata = {...frame.metadata, generation: ++generation, index: status.index};
  for (const listener of visuals) listener({metadata, payload: frame.payload} as WireFrame);
  for (const listener of events) listener({type: 'status', ...status});
}

function play() {
  clearInterval(timer);
  status = {...status, state: 'running'};
  let index = status.index;
  timer = setInterval(() => emit(++index), 1000 / fps);
}

const api: DesktopAPI = {
  info: async () => ({version: 'replay', platform: navigator.platform, status}),
  command: async (name: string, args: Json = {}) => {
    if (name === 'start') play();
    if (name === 'pause') {clearInterval(timer); status = {...status, state: 'paused'};}
    if (name === 'step') emit(status.index + 1);
    if (name === 'seek') emit(Number(args.index ?? 0));
    if (name === 'policy') status = {...status, policy: args.policy};
    if (name === 'layer') status = {...status, layer: args.layer};
    return {ok: true, status};
  },
  stop: async () => ({status}),
  configure: async () => ({status}),
  validateConfig: async () => ({ok: true}),
  chooseDataset: async () => null,
  openConfig: async () => null,
  saveConfig: async () => false,
  openReport: async () => null,
  exportReport: async () => false,
  loadBenchmarkArtifact: async () => { throw new Error('replay has no benchmark artifacts'); },
  diagnostics: async () => false,
  screenshot: async () => false,
  restart: async () => ({status}),
  onEvent: callback => {events.add(callback); return () => events.delete(callback);},
  onVisualization: callback => {visuals.add(callback); return () => visuals.delete(callback);},
};

await load();
window.veyra = api;
await import('../renderer/main');
emit(0);
if (params.get('autoplay') !== '0') play();
