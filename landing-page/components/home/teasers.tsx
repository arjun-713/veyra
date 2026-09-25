import Link from "next/link";
import Reveal from "../ui/Reveal";
import { EVIDENCE } from "../../lib/benchmark-data";
import { GITHUB_URL } from "../../lib/releases";
import "./teasers.css";

const HIGHLIGHTS = ["Logical map memory", "Active map cells", "Map-update latency p95", "Elevation RMSE vs Uniform5"];

function fmtValue(label: string): string {
  const metric = EVIDENCE.find((m) => m.label === label);
  if (!metric || metric.uniform5 === null || metric.adaptive === null) return "N/A";
  const fmt = (v: number) => {
    if (metric.unit === "MB") return `${v.toFixed(1)} MB`;
    if (metric.unit === "ms") return `${v.toFixed(0)} ms`;
    if (metric.unit === "m") return `${v.toFixed(2)} m`;
    return v.toLocaleString("en-US");
  };
  return `${fmt(metric.adaptive)} vs ${fmt(metric.uniform5)}`;
}

export function ResolutionTeaser() {
  return (
    <section className="section teaser" aria-labelledby="res-teaser">
      <div className="wrap teaser-grid">
        <div>
          <h2 id="res-teaser" className="display-lg">
            Near is fine.
            <br />
            Far is coarse.
          </h2>
          <p>
            <Link href="/technology">How resolution is assigned →</Link>
          </p>
        </div>
        <div className="teaser-bands" aria-hidden="true">
          {[
            ["L0 · 5 cm", "var(--lod-0)", 1],
            ["L1 · 10 cm", "var(--lod-1)", 2],
            ["L2 · 20 cm", "var(--lod-2)", 3],
            ["L3 · 40 cm", "var(--lod-3)", 4],
          ].map(([label, color, flex]) => (
            <span key={label as string} style={{ background: color as string, flex: flex as number }} title={label as string} />
          ))}
        </div>
      </div>
    </section>
  );
}

export function EvidenceHighlights() {
  return (
    <section className="section teaser" aria-labelledby="ev-teaser">
      <div className="wrap">
        <h2 id="ev-teaser" className="display-lg">
          Measured, not marketed.
        </h2>
        <dl className="highlight-grid">
          {HIGHLIGHTS.map((label, i) => (
            <Reveal key={label} delayMs={i * 60}>
              <div>
                <dt>{label}</dt>
                <dd className="measure">{fmtValue(label)}</dd>
              </div>
            </Reveal>
          ))}
        </dl>
        <p className="teaser-link">
          <Link href="/evidence">Full engineering report with provenance →</Link>
        </p>
      </div>
    </section>
  );
}

export function DownloadCta() {
  return (
    <section className="section teaser" aria-labelledby="dl-teaser">
      <div className="wrap download-cta">
        <h2 id="dl-teaser" className="display-lg">
          Run it on your machine.
        </h2>
        <div className="download-cta-row">
          <Link className="btn-download" href="/download">
            Download Veyra
          </Link>
          <a className="btn-explore" href={GITHUB_URL} target="_blank" rel="noreferrer">
            View on GitHub
          </a>
        </div>
      </div>
    </section>
  );
}
