import Reveal from "../ui/Reveal";
import { GITHUB_URL } from "../../lib/releases";
import "./Engineering.css";

/* Engineering credibility: the real stack, no logo cloud. */

const STACK = [
  { name: "C++20 mapper", detail: "Sparse world-aligned 2.5D map, LOD policy, governor — no CUDA required." },
  { name: "Python perception", detail: "Patchwork++ ground, ONNX/SalsaNext semantics, terrain and temporal stages." },
  { name: "Rust + Tauri desktop", detail: "Operator app with map, telemetry, benchmark and validation views." },
  { name: "Reproducible benchmarks", detail: "Digest-pinned streams, four-policy comparisons, CI regression gates." },
  { name: "Dataset adapters", detail: "SemanticKITTI, SemanticPOSS, RELLIS-3D and a generic manifest source." },
  { name: "Measured evidence", detail: "RSS, p50/p95/p99, RMSE, coverage, retention — analytical kept separate." },
];

export default function Engineering() {
  return (
    <section className="section" aria-labelledby="eng-title">
      <div className="wrap">
        <div className="section-head">
          <h2 id="eng-title">Built like infrastructure, not a demo.</h2>
          <p>
            The repository carries the mapper, the perception stages, the desktop
            app and the benchmark harness together — so every number on this page
            traces to code you can run.
          </p>
        </div>
        <ul className="stack-list">
          {STACK.map((item, i) => (
            <Reveal as="li" key={item.name} delayMs={Math.min(i, 5) * 60}>
              <h3>{item.name}</h3>
              <p>{item.detail}</p>
            </Reveal>
          ))}
        </ul>
        <Reveal>
          <p className="github-line">
            <a href={GITHUB_URL} target="_blank" rel="noreferrer">
              Read the code on GitHub →
            </a>
          </p>
        </Reveal>
      </div>
    </section>
  );
}
