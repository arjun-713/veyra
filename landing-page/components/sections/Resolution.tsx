"use client";

import { useState } from "react";
import Reveal from "../ui/Reveal";
import "./Resolution.css";

/* Interactive range rings: hover or tap a band to read its resolution. */

const BANDS = [
  { level: "L0", size: "5 cm", range: "0–10 m", color: "#33d9f2", r: 34, width: 26 },
  { level: "L1", size: "10 cm", range: "10–30 m", color: "#4dd980", r: 62, width: 28 },
  { level: "L2", size: "20 cm", range: "30–60 m", color: "#ffb340", r: 94, width: 32 },
  { level: "L3", size: "40 cm", range: "60–100 m", color: "#d966d9", r: 128, width: 34 },
] as const;

export default function Resolution() {
  const [active, setActive] = useState<number>(0);

  return (
    <section className="section" aria-labelledby="res-title">
      <div className="wrap resolution-grid">
        <div>
          <div className="section-head" style={{ marginBottom: 32 }}>
            <h2 id="res-title">Near is fine. Far is coarse. Always.</h2>
            <p>
              Distance sets the baseline resolution; utility evidence can only promote
              important cells finer. Select a band to inspect it.
            </p>
          </div>
          <ul className="band-list tnum">
            {BANDS.map((band, i) => (
              <li key={band.level}>
                <button
                  className={`band${active === i ? " is-active" : ""}`}
                  onClick={() => setActive(i)}
                  aria-pressed={active === i}
                  style={{ borderColor: active === i ? band.color : undefined }}
                >
                  <span className="band-dot" style={{ background: band.color }} aria-hidden="true" />
                  <strong>
                    {band.level} · {band.size}
                  </strong>
                  <span>{band.range}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="band-note">
            UtilityLOD promotions — geometry, semantics, motion, traversability risk —
            refine within these bands under an observation-quality gate, with hysteresis
            against split/merge churn and a governor that never coarsens the 10 m safety disk.
          </p>
        </div>
        <Reveal className="rings-figure">
          <figure aria-label={`Top-down resolution bands. Active: ${BANDS[active].level}, ${BANDS[active].size}, ${BANDS[active].range}`}>
            <svg viewBox="0 0 300 300" role="img" aria-hidden="true">
              {[...BANDS].reverse().map((band) => (
                <circle
                  key={band.level}
                  cx="150"
                  cy="150"
                  r={band.r}
                  fill="none"
                  stroke={band.color}
                  strokeWidth={band.width}
                  opacity={BANDS[active].level === band.level ? 0.85 : 0.22}
                  style={{ transition: "opacity 0.3s ease" }}
                />
              ))}
              <circle cx="150" cy="150" r="5" fill="#d7e3ed" />
              <circle cx="150" cy="150" r="10" fill="none" stroke="#62e0d7" strokeWidth="1.5" opacity="0.8" />
            </svg>
            <figcaption className="tnum">
              {BANDS[active].level} · {BANDS[active].size} · {BANDS[active].range}
            </figcaption>
          </figure>
        </Reveal>
      </div>
    </section>
  );
}
