import type {Json} from '../core.ts';

export function previewReadiness(catalog: Json | null, sequence: string, busy: boolean) {
  if (busy) return {ready: false, hint: 'Wait for the current operation to finish.'};
  if (!catalog?.root) return {ready: false, hint: 'Choose a dataset directory to continue.'};
  const selected = catalog.sequences?.find((entry: Json) => entry.id === sequence);
  if (!selected || !(selected.frames > 0)) {
    return {ready: false, hint: 'Select a sequence containing supported LiDAR frames.'};
  }
  return {ready: true, hint: 'Starts the backend and processes the first frame. Playback begins in Viewer.'};
}

export function sessionActive(status: Json): boolean {
  return ['ready', 'running', 'paused', 'ended'].includes(status.state) && !!status.dataset;
}

export function runtimeLabel(state: unknown): string {
  const labels: Record<string, string> = {
    unconfigured: 'No session', ready: 'Ready', running: 'Playing', paused: 'Paused',
    ended: 'Replay complete', stopped: 'Stopped', error: 'Needs attention',
    loading: 'Loading', stopping: 'Stopping', booting: 'Starting',
  };
  return typeof state === 'string' ? labels[state] ?? state : 'Connecting';
}

/** Recovery advice never replaces or hides the original backend diagnostic. */
export function errorRecovery(message: string): {title: string; action: string; restart: boolean} {
  if (/ModuleNotFoundError|ImportError|PYTHONHOME|failed to start|No such file.*python/i.test(message)) {
    return {title: 'Backend environment needs attention', action: 'Check the installed backend and Python dependencies. Export Diagnostics above; restarting alone cannot restore missing files.', restart: false};
  }
  if (/model.not.found|checkpoint|weights|GPU_PROVIDER_UNAVAILABLE|unsupported.*provider/i.test(message)) {
    return {title: 'Perception configuration needs attention', action: 'Review the model path and execution provider in Session setup → Advanced configuration. Model weights stay external.', restart: false};
  }
  if (/protocol|schema.version|Unsupported visualization schema/i.test(message)) {
    return {title: 'Desktop and backend versions do not match', action: 'Rebuild or reinstall the desktop and backend together. Export Diagnostics above to identify their versions.', restart: false};
  }
  if (/webgl|graphics context/i.test(message)) {
    return {title: 'Renderer needs attention', action: 'Check WebGL availability and graphics drivers. Export Diagnostics above; restarting the backend does not repair the renderer.', restart: false};
  }
  if (/JSON|SyntaxError|config|dataset|sequence|No supported frames/i.test(message)) {
    return {title: 'Session setup needs attention', action: 'Review the selected dataset, sequence and configuration. Correct the input, then open its preview again.', restart: false};
  }
  if (/runtime exited|process error|timed out|runtime.*not running|MAPPER_CRASHED|PERCEPTION_CRASHED/i.test(message)) {
    return {title: 'Runtime stopped unexpectedly', action: 'Export Diagnostics above for the exact process error. You can restart the session; if it fails again, check the technical detail below.', restart: true};
  }
  return {title: 'Operation could not complete', action: 'Check the technical detail and export Diagnostics above. The operation has not been marked successful.', restart: false};
}
