"use client";

import { useState } from "react";
import Reveal from "../ui/Reveal";
import "./Resolution.css";

const BANDS = [
  { level: "L0", size: "5 cm", range: "0–10 m", blurb: "Curbs, poles, feet. Full detail where steering happens.", color: "var(--lod-0)", r: 44 },
  { level: "L1", size: "10 cm", range: "10–30 m", blurb: "Lane geometry, vehicles, people. The operating band.", color: "var(--lod-1)", r: 78 },
  { level: "L2", size: "20 cm", range: "30–60 m", blurb: "Structures and road shape. Context, not control.", color: "var(--lod-2)", r: 112 },
  { level: "L3", size: "40 cm", range: "60–100 m", blurb: "Distant terrain. Bounded cost at the horizon.", color: "var(--lod-3)", r: 142 },
] as const;

export default function Resolution() {
  const [active, setActive] = useState(0);

  return (
    <section className="section" aria-labelledby="res-title">
      <div className="wrap">
        <div className="section-head">
          <h2 id="res-title" className="display-lg">
            Near is fine.
            <br />
            Far is coarse.
          </h2>
          <p className="body-lead">
            Distance sets the baseline; utility evidence can only promote important
            cells finer. Select a band to inspect it.
          </p>
        </div>
        <div className="rings-layout">
          <Reveal className="rings-stage">
            <figure aria-label={`Top-down resolution bands. Active: ${BANDS[active].level}, ${BANDS[active].size}, ${BANDS[active].range}`}>
              <svg viewBox="0 0 320 320" role="img" aria-hidden="true">
                <circle cx="160" cy="160" r="150" fill="#fff" />
                {[...BANDS].reverse().map((band) => (
                  <circle
                    key={band.level}
                    cx="160"
                    cy="160"
                    r={band.r}
                    fill="none"
                    stroke={band.color}
                    strokeWidth={band.r === 44 ? 30 : 26}
                    opacity={BANDS[active].level === band.level ? 0.75 : 0.22}
                    style={{ transition: "opacity 0.3s ease" }}
                  />
                ))}
                <circle cx="160" cy="160" r="16" fill="#0c1522" />
                <circle cx="160" cy="160" r="16" fill="none" stroke="#14b8b0" strokeWidth="2" />
                <circle cx="160" cy="160" r="7" fill="#5eead4" />
              </svg>
              <figcaption className="measure">
                {BANDS[active].level} · {BANDS[active].size} · {BANDS[active].range}
              </figcaption>
            </figure>
          </Reveal>
          <ol className="rings-list">
            {BANDS.map((band, i) => (
              <Reveal as="li" key={band.level} delayMs={i * 60}>
                <button
                  className={`ring-row${active === i ? " is-active" : ""}`}
                  onClick={() => setActive(i)}
                  aria-pressed={active === i}
                >
                  <span className="ring-swatch" style={{ background: band.color }} aria-hidden="true" />
                  <span className="ring-text">
                    <strong className="display-md">
                      {band.size} <span className="measure ring-range">{band.range}</span>
                    </strong>
                    <span className="ring-blurb">{band.blurb}</span>
                  </span>
                  <span className="measure ring-level">{band.level}</span>
                </button>
              </Reveal>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
