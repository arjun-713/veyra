import Reveal from "../ui/Reveal";
import { EVIDENCE, PROVENANCE, type EvidenceMetric } from "../../lib/benchmark-data";
import "./Evidence.css";

function formatValue(metric: EvidenceMetric): string {
  if (metric.uniform5 === null && metric.adaptive === null) return "N/A";
  const fmt = (v: number | null) => {
    if (v === null) return "—";
    if (metric.unit === "×") return `${v.toFixed(4)}×`;
    if (metric.unit === "m") return `${v.toFixed(v !== 0 && v < 1 ? 4 : 1)} m`;
    if (metric.unit === "MB") return `${v.toFixed(1)} MB`;
    if (metric.unit === "ms") return `${v.toFixed(0)} ms`;
    return v.toLocaleString("en-US");
  };
  if (metric.uniform5 !== null && metric.adaptive !== null) {
    return `${fmt(metric.adaptive)} · ${fmt(metric.uniform5)}`;
  }
  return fmt(metric.uniform5 ?? metric.adaptive);
}

export default function Evidence() {
  return (
    <section className="section" id="evidence" aria-labelledby="evidence-title">
      <div className="wrap">
        <div className="section-head">
          <p className="meta-label">ENGINEERING REPORT · DISTANCELOD VS UNIFORM5</p>
          <h2 id="evidence-title" className="display-lg">
            Measured,
            <br />
            not marketed.
          </h2>
          <p className="body-lead">
            Identical frames, identical perception, identical machine. The left
            value is the adaptive map; the right is the uniform baseline.
          </p>
        </div>
        <Reveal className="report-scroll">
          <table className="report-table">
            <thead>
              <tr>
                <th scope="col">Metric</th>
                <th scope="col">Adaptive · Uniform5</th>
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
                  <td className="measure">{formatValue(metric)}</td>
                  <td>
                    <span className={`chip chip-${metric.kind.toLowerCase()}`}>{metric.kind}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Reveal>
        <Reveal>
          <dl className="provenance measure">
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
            <div>
              <dt>Verdict</dt>
              <dd>{PROVENANCE.verdict}</dd>
            </div>
          </dl>
        </Reveal>
      </div>
    </section>
  );
}
