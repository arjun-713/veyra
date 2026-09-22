"use client";

import dynamic from "next/dynamic";
import { Component, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import "./Hero.css";
import { GITHUB_URL } from "../lib/releases";

const HeroScene = dynamic(() => import("./three/HeroScene"), {
  ssr: false,
  loading: () => <div className="hero-canvas-fallback" aria-hidden="true" />,
});

class SceneBoundary extends Component<{ children: ReactNode; onFail: () => void }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch() {
    this.props.onFail();
  }

  render() {
    if (this.state.failed) return null;
    return this.props.children;
  }
}

function webglAvailable(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

function useInView<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [inView, setInView] = useState(true);
  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), {
      threshold: 0.05,
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return { ref, inView };
}

function useMediaQuery(queryText: string): boolean {
  const [matches, setMatches] = useState(
    () => typeof window !== "undefined" && window.matchMedia(queryText).matches
  );
  useEffect(() => {
    const query = window.matchMedia(queryText);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [queryText]);
  return matches;
}

function useReducedMotion(): boolean {
  return useMediaQuery("(prefers-reduced-motion: reduce)");
}

function useCompact(): boolean {
  return useMediaQuery("(max-width: 760px), (pointer: coarse)");
}

const ANNOTATIONS = [
  { label: "2.5D MAP", value: "XY + height/stats", x: "6%", y: "14%" },
  { label: "ACTIVE RADIUS", value: "100 m", x: "78%", y: "12%" },
  { label: "ADAPTIVE CELLS", value: "5–40 cm", x: "80%", y: "66%" },
  { label: "SEMANTIC POINTS", value: "5 classes live", x: "5%", y: "68%" },
];

export default function Hero() {
  const { ref, inView } = useInView<HTMLElement>();
  const reduced = useReducedMotion();
  const compact = useCompact();
  const [gl, setGl] = useState<boolean | null>(null);

  useEffect(() => {
    // Client-only capability probe; state starts unknown so SSR HTML matches.
    queueMicrotask(() => setGl(webglAvailable()));
  }, []);

  const animate = !reduced && inView;
  const showScene = gl !== false;

  return (
    <section className="hero" ref={ref} aria-label="Veyra live mapping">
      <div className="hero-copy">
        <h1>
          Adaptive perception
          <br />
          for the terrain ahead.
        </h1>
        <p className="hero-sub">
          Veyra compresses sequential 3D LiDAR into a semantic, variable-resolution
          2.5D map — fine detail where it matters, coarse elsewhere. Memory-aware,
          real-time, and measured.
        </p>
        <div className="hero-ctas">
          <a className="btn-primary" href="#download">
            Download Veyra
          </a>
          <a className="btn-ghost" href="#technology">
            Explore the technology
          </a>
        </div>
        <dl className="hero-stats tnum">
          <div>
            <dt>Cell hierarchy</dt>
            <dd>5–40 cm</dd>
          </div>
          <div>
            <dt>Active radius</dt>
            <dd>100 m</dd>
          </div>
          <div>
            <dt>Cell reduction</dt>
            <dd>−61%*</dd>
          </div>
        </dl>
        <p className="hero-fine">*Measured DistanceLOD vs Uniform5, SemanticPOSS seq 00. See evidence.</p>
      </div>

      <div className="hero-stage">
        {showScene ? (
          <SceneBoundary onFail={() => setGl(false)}>
            <Suspense fallback={<div className="hero-canvas-fallback" aria-hidden="true" />}>
              <HeroScene compact={compact} animate={animate} frameloop={animate ? "always" : "never"} />
            </Suspense>
          </SceneBoundary>
        ) : (
          <div className="hero-static" role="img" aria-label="Static illustration of LiDAR points resolving into adaptive grid cells">
            <svg viewBox="0 0 400 300" aria-hidden="true">
              <g fill="none" stroke="#62e0d7" strokeWidth="1" opacity="0.5">
                <circle cx="200" cy="170" r="40" />
                <circle cx="200" cy="170" r="80" />
                <circle cx="200" cy="170" r="120" />
              </g>
              <g fill="#33d9f2" opacity="0.8">
                {Array.from({ length: 24 }, (_, i) => (
                  <rect key={i} x={170 + (i % 6) * 10} y={140 + Math.floor(i / 6) * 10} width="7" height="7" />
                ))}
              </g>
              <g fill="#ffb340" opacity="0.7">
                {Array.from({ length: 12 }, (_, i) => (
                  <rect key={i} x={110 + (i % 4) * 22} y={200 + Math.floor(i / 4) * 22} width="16" height="16" />
                ))}
              </g>
              <rect x="192" y="150" width="16" height="10" fill="#d7e3ed" />
              <rect x="198" y="138" width="4" height="12" fill="#62e0d7" />
            </svg>
          </div>
        )}
        <ul className="hero-annotations tnum" aria-hidden="true">
          {ANNOTATIONS.map((a) => (
            <li key={a.label} style={{ left: a.x, top: a.y }}>
              <strong>{a.label}</strong>
              <span>{a.value}</span>
            </li>
          ))}
        </ul>
        <p className="hero-schematic">Cell sizes exaggerated for illustration.</p>
      </div>
    </section>
  );
}
