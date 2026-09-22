import Reveal from "../ui/Reveal";
import "./Problem.css";

/* The problem: uniform grids waste state or destroy detail. Three density
   strips drawn from the same 100 m bookkeeping — analytical, labeled. */

const ROWS = [
  {
    name: "Uniform 5 cm",
    cells: "12.57M cells · 383.5 MB",
    verdict: "Exhaustive — and unaffordable on a robot.",
    bars: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    tone: "far" as const,
  },
  {
    name: "Uniform 40 cm",
    cells: "~196k cells · ~6 MB",
    verdict: "Cheap — but curbs, poles and people vanish.",
    bars: [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
    tone: "coarse" as const,
  },
  {
    name: "Veyra adaptive",
    cells: "~248k cells · measured 168 MB peak",
    verdict: "Fine where it matters. Coarse where it doesn't.",
    bars: [1, 1, 1, 1, 1, 0.6, 0.35, 0.35, 0.2, 0.2, 0.2, 0.2],
    tone: "near" as const,
  },
];

export default function Problem() {
  return (
    <section className="section" aria-labelledby="problem-title">
      <div className="wrap">
        <div className="section-head">
          <h2 id="problem-title">A uniform grid is the wrong bet in both directions.</h2>
          <p>
            Map everything at 5&nbsp;cm and a 100&nbsp;m radius needs millions of cells.
            Drop to 40&nbsp;cm everywhere and the detail a robot steers by disappears.
            Veyra spends fine cells near the robot and on what matters — nowhere else.
          </p>
        </div>
        <ol className="density-rows">
          {ROWS.map((row, i) => (
            <Reveal as="li" key={row.name} delayMs={i * 90}>
              <article className={`density-row tone-${row.tone}`}>
                <div className="density-meta">
                  <h3>{row.name}</h3>
                  <p className="tnum">{row.cells}</p>
                </div>
                <div className="density-bars" aria-hidden="true">
                  {row.bars.map((v, j) => (
                    <span key={j} style={{ opacity: 0.25 + v * 0.75, transform: `scaleY(${0.3 + v * 0.7})` }} />
                  ))}
                </div>
                <p className="density-verdict">{row.verdict}</p>
              </article>
            </Reveal>
          ))}
        </ol>
      </div>
    </section>
  );
}
