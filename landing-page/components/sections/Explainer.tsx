import Reveal from "../ui/Reveal";
import "./Explainer.css";

/* 2.5D, stated plainly: what a cell stores, and what it refuses to be. */

const FIELDS = [
  { name: "Elevation", detail: "Mean, min, max, variance — ground, obstacle and overhead layers kept separate." },
  { name: "Statistics", detail: "Point count, last-seen frame. Sufficient statistics only; raw points are never retained." },
  { name: "Semantics", detail: "Class + confidence. Class 0 is unknown with zero confidence — never a guess." },
  { name: "Traversability", detail: "Drivable / non-drivable / unknown. Unknown is never reported drivable." },
  { name: "Motion", detail: "Static, possibly-moving, moving. Dynamics never contaminate the terrain layers." },
];

export default function Explainer() {
  return (
    <section className="section" aria-labelledby="cell-title">
      <div className="wrap explainer-grid">
        <div>
          <div className="section-head" style={{ marginBottom: 32 }}>
            <h2 id="cell-title">Rendered in 3D. Stored as adaptive 2.5D cells.</h2>
            <p>
              Every visualisation you see is a rendering choice. The map itself is an
              XY lattice: one adaptive cell per ground location, carrying height and
              scene statistics — not a dense XYZ voxel volume.
            </p>
          </div>
          <p className="cell-formula tnum" aria-label="Cell contents">
            (X, Y) → elevation + statistics + semantics + traversability + motion
          </p>
          <ul className="cell-fields">
            {FIELDS.map((field, i) => (
              <Reveal as="li" key={field.name} delayMs={i * 60}>
                <strong>{field.name}</strong>
                <span>{field.detail}</span>
              </Reveal>
            ))}
          </ul>
        </div>
        <Reveal className="voxel-contrast" delayMs={120}>
          <figure>
            <figcaption className="tnum">NOT THIS — DENSE XYZ VOXELS</figcaption>
            <div className="voxel-stack" aria-hidden="true">
              {Array.from({ length: 27 }, (_, i) => (
                <span key={i} />
              ))}
            </div>
            <p>
              A dense 5&nbsp;cm volume over 100&nbsp;m is ~12.57M cells whether anything
              is there or not. Veyra pays for surfaces it observed — nothing else.
            </p>
          </figure>
        </Reveal>
      </div>
    </section>
  );
}
