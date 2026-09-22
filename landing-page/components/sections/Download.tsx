"use client";

import { useEffect, useState } from "react";
import Reveal from "../ui/Reveal";
import { GITHUB_URL, RELEASES, SOURCE_BUILD } from "../../lib/releases";
import "./Download.css";

function platformGuess(): string {
  if (typeof navigator === "undefined") return "";
  const platform = navigator.platform.toLowerCase();
  const agent = navigator.userAgent.toLowerCase();
  if (platform.includes("mac") || agent.includes("mac os")) return "macOS";
  if (platform.includes("win")) return "Windows";
  return "Linux";
}

export default function Download() {
  const [os, setOs] = useState("");

  useEffect(() => {
    // Client-only platform hint; deferred so the first paint matches SSR.
    queueMicrotask(() => setOs(platformGuess()));
  }, []);

  const ordered = [...RELEASES].sort((a, b) => {
    if (!os) return 0;
    if (a.os === os && b.os !== os) return -1;
    if (b.os === os && a.os !== os) return 1;
    return 0;
  });

  return (
    <section className="section" id="download" aria-labelledby="download-title">
      <div className="wrap">
        <div className="section-head">
          <h2 id="download-title">Run it on your machine.</h2>
          <p>
            Packaged installers follow the release workflow; until the first
            tagged release, every card states its status honestly and the source
            build below always works.
            {os ? (
              <>
                {" "}
                Detected platform: <strong className="tnum">{os}</strong> — its
                options are listed first.
              </>
            ) : null}
          </p>
        </div>
        <ul className="release-grid">
          {ordered.map((release, i) => (
            <Reveal as="li" key={release.id} delayMs={Math.min(i, 5) * 60}>
              <article className={`release${release.status === "coming-soon" ? " is-soon" : ""}`}>
                <p className="release-os tnum">{release.os}</p>
                <h3>{release.title}</h3>
                <p className="release-detail">{release.detail}</p>
                <dl className="release-meta tnum">
                  <div>
                    <dt>Arch</dt>
                    <dd>{release.arch}</dd>
                  </div>
                  <div>
                    <dt>Format</dt>
                    <dd>{release.format}</dd>
                  </div>
                </dl>
                {release.status === "available" && release.url ? (
                  <a className="release-btn" href={release.url}>
                    Download{release.size ? ` · ${release.size}` : ""}
                  </a>
                ) : (
                  <p className="release-soon">
                    <strong>Coming soon.</strong> {release.reason}
                  </p>
                )}
              </article>
            </Reveal>
          ))}
        </ul>
        <Reveal>
          <div className="source-build">
            <div>
              <h3>Build from source</h3>
              <p>Core mapper needs only C++20 and CMake. CUDA is optional.</p>
            </div>
            <code className="tnum">{SOURCE_BUILD.command}</code>
            <a className="btn-ghost" href={GITHUB_URL} target="_blank" rel="noreferrer">
              View on GitHub
            </a>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
