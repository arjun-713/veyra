import Reveal from "../ui/Reveal";
import "./Problem.css";

const COMPARISON = [
  {
    name: "Uniform 5 cm",
    outcome: "huge state",
    figure: "12.57M cells · 383.5 MB",
    note: "Every square metre at full detail, whether the robot needs it or not.",
    density: 1,
  },
  {
    name: "Uniform 40 cm",
    outcome: "low detail",
    figure: "~196k cells · pedestrian recall −22 pts",
    note: "Cheap to store — and blind to the thin geometry steering depends on.",
    density: 0.14,
  },
  {
    name: "Veyra adaptive",
    outcome: "resolution follows need",
    figure: "146k cells · 25.8 MB · RMSE 0.43 m",
    note: "5 cm near the robot and on what matters; 40 cm everywhere else. Measured.",
    density: 0,
    adaptive: true,
  },
];

export default function Problem() {
  return (
    <section className="section" aria-labelledby="problem-title">
      <div className="wrap">
        <div className="section-head">
          <h2 id="problem-title" className="display-lg">
            Fine everywhere is expensive.
            <br />
            Coarse everywhere loses detail.
          </h2>
          <p className="body-lead">
            A 100 m radius at 5 cm everywhere is millions of cells of mostly empty
            space. At 40 cm everywhere, poles and pedestrians dissolve. The map
            should spend detail where losing it costs something.
          </p>
        </div>
        <Reveal>
          <div className="comparison">
            {COMPARISON.map((row) => (
              <div className="comparison-row" key={row.name}>
                <div className="comparison-name">
                  <h3 className="display-md">{row.name}</h3>
                  <p className="measure">{row.outcome}</p>
                </div>
                {row.adaptive ? (
                  <div className="adaptive-bar" aria-hidden="true">
                    {["L0", "L1", "L2", "L3"].map((level, i) => (
                      <span key={level} style={{ flex: [1, 2, 3, 4][i] }} data-level={level} />
                    ))}
                  </div>
                ) : (
                  <div
                    className="uniform-bar"
                    aria-hidden="true"
                    style={{ opacity: 0.25 + row.density * 0.75 }}
                  >
                    {Array.from({ length: 24 }, (_, i) => (
                      <span key={i} style={{ transform: `scaleY(${0.25 + row.density * 0.75})` }} />
                    ))}
                  </div>
                )}
                <div className="comparison-evidence">
                  <p className="measure">{row.figure}</p>
                  <p>{row.note}</p>
                </div>
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}
