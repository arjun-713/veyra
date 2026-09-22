"use client";

import Reveal from "../ui/Reveal";
import "./Showcase.css";

/* App showcase. Real captures drop into public/screenshots/ under these exact
   filenames; until then, labeled placeholders hold the layout. */

const SHOTS = [
  { file: "map.png", title: "Live mapping", detail: "Raw cloud, adaptive cells, resolution layers." },
  { file: "performance.png", title: "Performance", detail: "FPS, latency tails, memory domains." },
  { file: "compare.png", title: "Compare", detail: "Uniform vs adaptive benchmark evidence." },
  { file: "validation.png", title: "Validation", detail: "Session checks with PASS / FAIL." },
];

export default function Showcase() {
  return (
    <section className="section" id="app" aria-labelledby="app-title">
      <div className="wrap">
        <div className="section-head">
          <h2 id="app-title">The operator sees the proof, not the logs.</h2>
          <p>
            The desktop app renders the map, the resolution distribution, the
            telemetry and the benchmark comparison side by side — every claim
            inspectable without opening source.
          </p>
        </div>
        <div className="shot-grid">
          {SHOTS.map((shot, i) => (
            <Reveal key={shot.file} delayMs={i * 80}>
              <figure className="shot">
                <div className="shot-frame">
                  <div className="shot-bar" aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </div>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`/screenshots/${shot.file}`}
                    alt={`${shot.title} — application screenshot`}
                    loading="lazy"
                    onError={(event) => {
                      (event.currentTarget as HTMLImageElement).style.display = "none";
                    }}
                  />
                  <div className="shot-body">
                    <div className="shot-empty" aria-hidden="true">
                      <p>{shot.title}</p>
                      <p>Screenshot coming soon</p>
                    </div>
                  </div>
                </div>
                <figcaption>
                  <strong>{shot.title}</strong>
                  <span>{shot.detail}</span>
                </figcaption>
              </figure>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
