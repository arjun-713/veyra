// Replay-aware metric display: recorded cache measurements are labeled
// RECORDED, anything the cache does not store renders N/A — live values
// are never reused while replaying a cached run.

export function formatRecorded(value: unknown, format: (v: number) => string): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'N/A DURING REPLAY';
  return `${format(value)} · RECORDED`;
}

// Compact form for dense overlays (Judge View strip): the chip shows the bare
// value or "N/A"; the full honesty label (formatRecorded) stays in `title`,
// and the strip carries one visible RECORDED tag for the whole row.
export function compactRecorded(value: unknown, format: (v: number) => string): {text: string; title: string} {
  const full = formatRecorded(value, format);
  if (typeof value !== 'number' || !Number.isFinite(value)) return {text: 'N/A', title: full};
  return {text: format(value), title: full};
}

// Policy chip source: the replay cache header while replaying, else live
// status. Frame payloads carry no policy of their own.
export function replayPolicyName(status: {replay?: {active?: boolean; policy?: unknown} | null; policy?: unknown} | null | undefined): string | null {
  const replayPolicy = status?.replay?.active === true ? status?.replay?.policy : undefined;
  const name = replayPolicy ?? status?.policy;
  return typeof name === 'string' && name ? name : null;
}
