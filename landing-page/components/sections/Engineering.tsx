import Reveal from "../ui/Reveal";
import { GITHUB_URL } from "../../lib/releases";
import "./Engineering.css";

const STACK = [
  { name: "C++20 adaptive map", detail: "Sparse world-aligned 2.5D cells, LOD policy, runtime governor." },
  { name: "Python perception", detail: "Ground, semantics, terrain and temporal stages with measured latency." },
  { name: "Rust / Tauri desktop", detail: "Operator app: map, telemetry, benchmark comparison, validation." },
  { name: "ONNX Runtime", detail: "CPU semantic inference behind a swappable provider boundary." },
  { name: "Three.js visualization", detail: "Decimated live views; mapping latency measured separately." },
  { name: "Reproducible benchmarks", detail: "Digest-pinned streams, four-policy matrix, CI regression gates." },
];

export default function Engineering() {
  return (
    <section className="section" aria-labelledby="eng-title">
      <div className="wrap eng-grid">
        <div className="section-head" style={{ marginBottom: 0 }}>
          <h2 id="eng-title" className="display-lg">
            Built like
            <br />
            infrastructure.
          </h2>
          <p className="body-lead">
            Mapper, perception, desktop and harness ship in one repository — so
            every number on this page traces to code you can run.{" "}
            <a className="eng-link" href={GITHUB_URL} target="_blank" rel="noreferrer">
              Read it on GitHub →
            </a>
          </p>
        </div>
        <ul className="eng-list">
          {STACK.map((item, i) => (
            <Reveal as="li" key={item.name} delayMs={Math.min(i, 5) * 50}>
              <h3>{item.name}</h3>
              <p>{item.detail}</p>
            </Reveal>
          ))}
        </ul>
      </div>
    </section>
  );
}
