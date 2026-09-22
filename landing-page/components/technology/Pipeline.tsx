import Reveal from "../ui/Reveal";
import "./Pipeline.css";

const STAGES = [
  { index: "01", name: "Raw LiDAR", detail: "Sequential scans with external pose — tens of thousands of points per frame.", meta: "INPUT" },
  { index: "02", name: "Perception", detail: "Semantic labels with confidence, ground segmentation, terrain geometry.", meta: "SEE" },
  { index: "03", name: "Terrain + Motion", detail: "Drivable surface, slope and step — with static and moving tracks kept apart.", meta: "UNDERSTAND" },
  { index: "04", name: "Adaptive 2.5D Map", detail: "Sparse world-aligned cells at 5–40 cm. Distance sets the baseline; utility promotes.", meta: "MAP" },
];

export default function Pipeline() {
  return (
    <section className="section" id="technology" aria-labelledby="pipeline-title">
      <div className="wrap">
        <div className="section-head">
          <h2 id="pipeline-title" className="display-lg">
            From photons
            <br />
            to drivable cells.
          </h2>
          <p className="body-lead">
            One straight pipeline. The map never stores raw points — only sufficient
            statistics per cell — so state stays bounded while evidence stays honest.
          </p>
        </div>
        <ol className="flow">
          {STAGES.map((stage, i) => (
            <Reveal as="li" key={stage.name} delayMs={i * 70}>
              <span className="flow-index measure" aria-hidden="true">
                {stage.index}
              </span>
              <p className="flow-meta measure">{stage.meta}</p>
              <h3 className="display-md">{stage.name}</h3>
              <p className="flow-detail">{stage.detail}</p>
            </Reveal>
          ))}
        </ol>
      </div>
    </section>
  );
}
