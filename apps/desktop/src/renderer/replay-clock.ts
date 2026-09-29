// Smooth-replay presentation clock: deterministic dataset-frame scheduling
// decoupled from backend processing.
//
// The renderer runs at display refresh (~60 Hz via requestAnimationFrame).
// The replay clock maps accumulated replay time onto cached snapshot indices
// at REPLAY_FPS (default 30 dataset frames/sec ≈ 33.333 ms per snapshot).
// At 60 Hz that is roughly two render refreshes per LiDAR frame.
//
// LATEST FRAME WINS: if the UI stalls, the clock jumps to the snapshot for
// the current replay time instead of queueing every missed frame. Missed
// snapshots count as presentation_drops — a presentation metric, unrelated
// to backend processing drops.
//
// Replay FPS is a PRESENTATION rate, never processing throughput.

export const REPLAY_DEFAULT_FPS = 30;
export const REPLAY_FPS_OPTIONS = [15, 30, 60] as const;
export const REPLAY_SPEED_OPTIONS = [0.5, 1, 2] as const;

export interface ReplayClockSample {
  presentedIndex: number;
  atMs: number;
  intervalMs: number | null;
  dropped: number;
}

export interface ReplayClockStats {
  targetFps: number;
  presented: number;
  presentationDrops: number;
  bufferUnderruns: number;
  intervals: number[];
  lastIndex: number;
}

export function percentile(sorted: number[], q: number): number | null {
  if (!sorted.length) return null;
  const rank = q * (sorted.length - 1);
  const lower = Math.floor(rank), upper = Math.ceil(rank);
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (rank - lower);
}

export class ReplayClock {
  fps = REPLAY_DEFAULT_FPS;
  speed = 1;
  totalFrames = 0;
  replayTimeMs = 0;
  lastPresented = -1;
  running = false;
  presented = 0;
  presentationDrops = 0;
  bufferUnderruns = 0;
  private intervals: number[] = [];
  private lastPresentAt: number | null = null;

  constructor(totalFrames = 0, fps = REPLAY_DEFAULT_FPS) {
    this.totalFrames = totalFrames;
    this.fps = fps;
  }

  get frameIntervalMs(): number {
    return 1000 / (this.fps * this.speed);
  }

  get desiredIndex(): number {
    return Math.floor((this.replayTimeMs / 1000) * this.fps * this.speed);
  }

  get durationMs(): number {
    return this.totalFrames > 0 ? (this.totalFrames / this.fps) * 1000 : 0;
  }

  start(): void {
    this.running = true;
  }

  pause(): void {
    this.running = false;
  }

  restart(): void {
    this.replayTimeMs = 0;
    this.lastPresented = -1;
    this.running = true;
  }

  seekToFrame(index: number): void {
    const clamped = Math.max(0, Math.min(this.totalFrames - 1, Math.floor(index)));
    this.replayTimeMs = (clamped / (this.fps * this.speed)) * 1000;
    this.lastPresented = clamped - 1;
  }

  /** Advance the clock by elapsed wall time. Returns the snapshot index to
   * present, or null when nothing new is due. Latest-wins: a stall jumps
   * forward and counts every skipped snapshot as a presentation drop. */
  advance(elapsedMs: number, newestAvailable: number, nowMs: number): ReplayClockSample | null {
    if (!this.running || this.totalFrames <= 0) return null;
    this.replayTimeMs += Math.max(0, elapsedMs);
    let desired = this.desiredIndex;
    if (desired >= this.totalFrames) desired = this.totalFrames - 1;
    if (desired <= this.lastPresented) return null;
    // Never present a snapshot that has not arrived yet; hold at the newest
    // available frame and count a buffer underrun (prefetch fell behind).
    const present = Math.min(desired, newestAvailable);
    if (present <= this.lastPresented) {
      this.bufferUnderruns += 1;
      return null;
    }
    const dropped = present - this.lastPresented - 1;
    this.presentationDrops += dropped;
    this.lastPresented = present;
    this.presented += 1;
    let interval: number | null = null;
    if (this.lastPresentAt !== null) {
      interval = nowMs - this.lastPresentAt;
      this.intervals.push(interval);
      if (this.intervals.length > 1800) this.intervals.splice(0, this.intervals.length - 1800);
    }
    this.lastPresentAt = nowMs;
    return { presentedIndex: present, atMs: nowMs, intervalMs: interval, dropped };
  }

  get finished(): boolean {
    return this.totalFrames > 0 && this.lastPresented >= this.totalFrames - 1;
  }

  snapshot(): ReplayClockStats {
    return {
      targetFps: this.fps * this.speed,
      presented: this.presented,
      presentationDrops: this.presentationDrops,
      bufferUnderruns: this.bufferUnderruns,
      intervals: [...this.intervals],
      lastIndex: this.lastPresented,
    };
  }

  jitterReport(): { p50: number | null; p95: number | null; max: number | null; count: number } {
    const sorted = [...this.intervals].sort((a, b) => a - b);
    return {
      p50: percentile(sorted, 0.5),
      p95: percentile(sorted, 0.95),
      max: sorted.length ? sorted[sorted.length - 1] : null,
      count: sorted.length,
    };
  }

  resetStats(): void {
    this.presented = 0;
    this.presentationDrops = 0;
    this.bufferUnderruns = 0;
    this.intervals = [];
    this.lastPresentAt = null;
  }
}

// Bounded prefetch window bookkeeping: how many decoded snapshots are held
// ahead of the playhead. The backend keeps the same kind of byte-bounded
// ring; this mirror lets the UI display prefetch health without copying data.
export class PrefetchWindow {
  readonly capacity: number;
  private held = new Map<number, number>();

  constructor(capacity = 48) {
    this.capacity = capacity;
  }

  note(index: number, bytes: number): void {
    this.held.set(index, bytes);
    while (this.held.size > this.capacity) {
      const oldest = this.held.keys().next().value;
      if (oldest === undefined) break;
      this.held.delete(oldest);
    }
  }

  releaseThrough(index: number): void {
    for (const key of [...this.held.keys()]) if (key <= index) this.held.delete(key);
  }

  clear(): void {
    this.held.clear();
  }

  get size(): number {
    return this.held.size;
  }

  get bytes(): number {
    let total = 0;
    for (const value of this.held.values()) total += value;
    return total;
  }
}
