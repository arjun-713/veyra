import Reveal from "../ui/Reveal";
import "./Explainer.css";

const FIELDS = [
  { name: "Height statistics", detail: "Mean, min, max, variance — ground, obstacle and overhead layers kept separate." },
  { name: "Semantic class", detail: "Class plus confidence. Unknown stays unknown at zero confidence." },
  { name: "Traversability", detail: "Drivable, non-drivable, unknown — and unknown is never drivable." },
  { name: "Motion / state", detail: "Static, possibly-moving, moving. Dynamics never contaminate terrain." },
];

export default function Explainer() {
  return (
    <section className="section" aria-labelledby="cell-title">
      <div className="wrap">
        <div className="section-head">
          <h2 id="cell-title" className="display-lg">
            Rendered spatially.
            <br />
            Stored efficiently.
          </h2>
        </div>
        <div className="cell-grid">
          <Reveal>
            <div className="cell-diagram" aria-label="One XY cell expands into height, semantics, traversability and motion">
              <p className="measure cell-xy">(X, Y)</p>
              <div className="cell-arrows" aria-hidden="true">
                <span />
                <span />
                <span />
                <span />
              </div>
              <ul>
                {FIELDS.map((field) => (
                  <li key={field.name}>
                    <strong>{field.name}</strong>
                    <span>{field.detail}</span>
                  </li>
                ))}
              </ul>
            </div>
          </Reveal>
          <Reveal delayMs={120}>
            <div className="voxel-note">
              <p className="meta-label">NOT THIS</p>
              <div className="voxel-field" aria-hidden="true">
                {Array.from({ length: 64 }, (_, i) => (
                  <span key={i} style={{ opacity: 0.25 + ((i * 37) % 10) / 14 }} />
                ))}
              </div>
              <p>
                A dense 5 cm volume over 100 m is an estimated 7.33 billion cells
                whether anything is there or not. Veyra pays for surfaces it
                observed — roughly 146k cells on the measured selection.
              </p>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
