import Reveal from "../ui/Reveal";
import { EVIDENCE, PROVENANCE, SINGLE_FRAME_PROBE, type EvidenceMetric } from "../../lib/benchmark-data";
import "./Evidence.css";

function formatValue(metric: EvidenceMetric): string {
  if (metric.uniform5 === null && metric.adaptive === null) return "N/A";
  const fmt = (v: number | null) => {
    if (v === null) return "—";
    if (metric.unit === "×") return `${v.toFixed(v < 1 && v > 0 ? 4 : 2)}×`;
    if (metric.unit === "m") return `${v.toFixed(v < 1 && v > 0 ? 5 : 2)} m`;
    if (metric.unit === "MB") return `${v.toFixed(1)} MB`;
    if (metric.unit === "ms") return `${v.toFixed(1)} ms`;
    return v.toLocaleString("en-US");
  };
  if (metric.uniform5 !== null && metric.adaptive !== null) {
    return `${fmt(metric.adaptive)} vs ${fmt(metric.uniform5)}`;
  }
  return fmt(metric.uniform5 ?? metric.adaptive);
}

export default function Evidence() {
  return (
    <section className="section" id="evidence" aria-labelledby="evidence-title">
      <div className="wrap">
        <div className="section-head">
          <h2 id="evidence-title">Measured, not marketed.</h2>
          <p>
            DistanceLOD against Uniform5 on identical frames — same stream, same
            perception, same machine. Every value keeps its evidence semantics.
          </p>
        </div>
        <Reveal>
          <div className="evidence-table-wrap">
            <table className="evidence-table tnum">
              <thead>
                <tr>
                  <th scope="col">Metric</th>
                  <th scope="col">Adaptive vs Uniform5</th>
                  <th scope="col">Source</th>
                </tr>
              </thead>
              <tbody>
                {EVIDENCE.map((metric) => (
                  <tr key={metric.label}>
                    <th scope="row">
                      {metric.label}
                      <span>{metric.note}</span>
                    </th>
                    <td>{formatValue(metric)}</td>
                    <td>
                      <span className={`chip chip-${metric.kind.toLowerCase()}`}>{metric.kind}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Reveal>
        <div className="provenance-grid">
          <Reveal>
            <div className="provenance-card">
              <h3>Provenance</h3>
              <dl className="tnum">
                <div>
                  <dt>Selection</dt>
                  <dd>{PROVENANCE.selection}</dd>
                </div>
                <div>
                  <dt>Hardware</dt>
                  <dd>{PROVENANCE.hardware}</dd>
                </div>
                <div>
                  <dt>Reference</dt>
                  <dd>{PROVENANCE.reference}</dd>
                </div>
              </dl>
            </div>
          </Reveal>
          <Reveal delayMs={100}>
            <div className="provenance-card">
              <h3>Single-frame probe</h3>
              <p>{SINGLE_FRAME_PROBE.selection}. {SINGLE_FRAME_PROBE.note}</p>
              <dl className="tnum">
                <div>
                  <dt>Uniform5</dt>
                  <dd>
                    {SINGLE_FRAME_PROBE.uniform5.leaves.toLocaleString()} leaves ·{" "}
                    {SINGLE_FRAME_PROBE.uniform5.logicalMB} MB · {SINGLE_FRAME_PROBE.uniform5.mapMs} ms ·{" "}
                    {SINGLE_FRAME_PROBE.uniform5.fps} fps
                  </dd>
                </div>
                <div>
                  <dt>DistanceLOD</dt>
                  <dd>
                    {SINGLE_FRAME_PROBE.distanceLod.leaves.toLocaleString()} leaves ·{" "}
                    {SINGLE_FRAME_PROBE.distanceLod.logicalMB} MB · {SINGLE_FRAME_PROBE.distanceLod.mapMs} ms ·{" "}
                    {SINGLE_FRAME_PROBE.distanceLod.fps} fps
                  </dd>
                </div>
              </dl>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
