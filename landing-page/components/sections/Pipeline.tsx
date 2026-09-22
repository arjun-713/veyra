import Reveal from "../ui/Reveal";
import "./Pipeline.css";

/* The system: five stages, one straight story. Pure CSS/SVG linework. */

const STAGES = [
  {
    name: "Raw LiDAR",
    detail: "Sequential scans + external pose. 60–100k points a frame on SemanticPOSS.",
    tag: "INPUT",
  },
  {
    name: "Semantic perception",
    detail: "Ground-truth or ONNX/SalsaNext labels with confidence. Unknown stays unknown.",
    tag: "PERCEIVE",
  },
  {
    name: "Terrain + motion",
    detail: "Patchwork++ ground, slope/roughness/step, static vs moving tracks.",
    tag: "UNDERSTAND",
  },
  {
    name: "Adaptive 2.5D map",
    detail: "Sparse world-aligned XY cells. 5 / 10 / 20 / 40 cm by distance, promoted by utility.",
    tag: "MAP",
  },
  {
    name: "Runtime governor",
    detail: "Watches cells, bytes, frame time. Merges low-value far cells first — never the safety disk.",
    tag: "GOVERN",
  },
];

export default function Pipeline() {
  return (
    <section className="section" id="technology" aria-labelledby="pipeline-title">
      <div className="wrap">
        <div className="section-head">
          <h2 id="pipeline-title">One pipeline, from photons to drivable cells.</h2>
          <p>
            Every scan flows through the same five stages. The map never stores raw
            points — only sufficient statistics per cell — so the state stays bounded
            while the evidence stays honest.
          </p>
        </div>
        <ol className="pipeline">
          {STAGES.map((stage, i) => (
            <Reveal as="li" key={stage.name} delayMs={i * 70}>
              <article className="stage">
                <p className="stage-tag tnum">{stage.tag}</p>
                <h3>{stage.name}</h3>
                <p>{stage.detail}</p>
              </article>
            </Reveal>
          ))}
        </ol>
      </div>
    </section>
  );
}
