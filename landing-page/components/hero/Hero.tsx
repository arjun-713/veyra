"use client";

import { useState } from "react";
import "./Hero.css";
import { HERO_REDUCTION } from "../../lib/benchmark-data";

const HERO_SRC = "/hero/veyra-lidar-map.webp";

const LABELS = [
  { title: "2.5D MAP", value: "XY + elevation statistics", x: "4%", y: "30%" },
  { title: "ACTIVE RADIUS", value: "100 m", x: "82%", y: "16%" },
  { title: "ADAPTIVE CELLS", value: "5–40 cm", x: "84%", y: "68%" },
  { title: "SEMANTIC POINTS", value: "Live classes", x: "2%", y: "64%" },
];

function HeroFallback() {
  return (
    <svg className="hero-fallback-art" viewBox="0 0 640 520" role="img" aria-label="Stylised top-down view of adaptive map rings around a robot">
      {[230, 175, 120, 70].map((r, i) => (
        <circle
          key={r}
          cx="330"
          cy="260"
          r={r}
          fill="none"
          stroke={["#a855f7", "#d97706", "#16a34a", "#0891b2"][i]}
          strokeWidth={26 - i * 4}
          opacity={0.5}
        />
      ))}
      <g fill="#0b6e6c" opacity="0.75">
        {Array.from({ length: 60 }, (_, i) => (
          <circle key={i} cx={120 + ((i * 53) % 420)} cy={60 + ((i * 91) % 400)} r={2.2} />
        ))}
      </g>
      <rect x="312" y="242" width="36" height="22" rx="5" fill="#0c1522" />
      <rect x="326" y="228" width="8" height="14" rx="3" fill="#14b8b0" />
    </svg>
  );
}

export default function Hero() {
  const [imgMissing, setImgMissing] = useState(false);

  return (
    <section className="hero" aria-label="Veyra introduction">
      <div className="hero-copy">
        <p className="eyebrow">SPATIAL AI FOR A MORE CAPABLE WORLD</p>
        <h1 className="display-xl">
          Adaptive
          <br />
          perception
          <br />
          for the terrain
          <br />
          ahead<span className="hero-dot">.</span>
        </h1>
        <p className="body-lead hero-sub">
          Veyra turns raw LiDAR into a semantic, adaptive 2.5D map — preserving
          fine detail where it matters while reducing unnecessary map state.
        </p>
        <div className="hero-ctas">
          <a className="btn-download" href="#download">
            <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
              <path
                d="M8 2v8m0 0L4.5 6.5M8 10l3.5-3.5M2.5 13.5h11"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            Download Veyra
          </a>
          <a className="btn-explore" href="#technology">
            Explore the technology
            <span aria-hidden="true">→</span>
          </a>
        </div>
        <dl className="hero-metrics">
          <div>
            <dt>Cell resolution</dt>
            <dd className="measure">5–40 cm</dd>
          </div>
          <div>
            <dt>Active radius</dt>
            <dd className="measure">100 m</dd>
          </div>
          <div>
            <dt>{HERO_REDUCTION.label}</dt>
            <dd className="measure">
              {HERO_REDUCTION.value}
              {HERO_REDUCTION.unit}
            </dd>
          </div>
        </dl>
        <p className="hero-fine">{HERO_REDUCTION.footnote}</p>
      </div>

      <div className="hero-visual">
        <HeroFallback />
        {!imgMissing && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            className="hero-image"
            src={HERO_SRC}
            alt=""
            aria-hidden="true"
            fetchPriority="high"
            onError={() => setImgMissing(true)}
          />
        )}
        <ul className="hero-labels" aria-label="Scene annotations">
          {LABELS.map((label) => (
            <li key={label.title} style={{ left: label.x, top: label.y }}>
              <strong className="measure">{label.title}</strong>
              <span className="measure">{label.value}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="hero-strip">
        <div className="hero-strip-group">
          <p>
            <strong>Richer maps.</strong> Where it matters.
          </p>
          <p>
            <strong>Faster decisions.</strong> In real time.
          </p>
          <p>
            <strong>Smarter autonomy.</strong> Across any terrain.
          </p>
        </div>
        <p className="hero-strip-note measure">FROM SENSORS TO A DEEPER UNDERSTANDING</p>
      </div>
    </section>
  );
}
