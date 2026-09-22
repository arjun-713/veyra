"use client";

import Reveal from "../ui/Reveal";
import "./Showcase.css";

const SHOTS = [
  { file: "map.webp", title: "Live mapping", detail: "Raw cloud, adaptive cells, resolution layers." },
  { file: "performance.webp", title: "Performance", detail: "FPS, latency tails, memory domains." },
  { file: "compare.webp", title: "Compare", detail: "Uniform vs adaptive benchmark evidence." },
  { file: "validation.webp", title: "Validation", detail: "Session checks with PASS / FAIL." },
];

export default function Showcase() {
  return (
    <section className="section" id="app" aria-labelledby="app-title">
      <div className="wrap">
        <div className="section-head">
          <h2 id="app-title" className="display-lg">
            The operator sees
            <br />
            the proof, not the logs.
          </h2>
          <p className="body-lead">
            Map, resolution distribution, telemetry and benchmark comparison side
            by side — every claim inspectable without opening source.
          </p>
        </div>
        <div className="shot-feature">
          {SHOTS.map((shot, i) => (
            <Reveal key={shot.file} delayMs={i * 70}>
              <figure className="shot">
                <div className="shot-frame">
                  <div className="shot-bar" aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </div>
                  <div className="shot-body">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`/screenshots/${shot.file}`}
                      alt={`${shot.title} — application screenshot`}
                      loading="lazy"
                      onError={(event) => {
                        (event.currentTarget as HTMLImageElement).style.display = "none";
                      }}
                    />
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
