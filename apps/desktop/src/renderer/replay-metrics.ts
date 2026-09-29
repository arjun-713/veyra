// Replay-aware metric display: recorded cache measurements are labeled
// RECORDED, anything the cache does not store renders N/A — live values
// are never reused while replaying a cached run.

export function formatRecorded(value: unknown, format: (v: number) => string): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'N/A DURING REPLAY';
  return `${format(value)} · RECORDED`;
}

// Policy chip source: the replay cache header while replaying, else live
// status. Frame payloads carry no policy of their own.
export function replayPolicyName(status: {replay?: {active?: boolean; policy?: unknown} | null; policy?: unknown} | null | undefined): string | null {
  const replayPolicy = status?.replay?.active === true ? status?.replay?.policy : undefined;
  const name = replayPolicy ?? status?.policy;
  return typeof name === 'string' && name ? name : null;
}
