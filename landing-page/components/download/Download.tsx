"use client";

import { useEffect, useRef, useState } from "react";
import Reveal from "../ui/Reveal";
import {
  RELEASES,
  RELEASES_URL,
  SOURCE_BUILD,
  formatAssetSize,
  matchReleaseAssets,
  type OSName,
  type PublishedReleaseAsset,
  type ReleaseArtifactId,
  type ReleaseLookupResponse,
} from "../../lib/releases";
import "./Download.css";

const OS_TABS: OSName[] = ["Linux", "Windows", "macOS"];

const OS_BLURB: Record<OSName, string> = {
  Linux: "Deb and rpm packages, plus a portable AppImage.",
  Windows: "One installer for Windows 10 and 11.",
  macOS: "Disk images for Apple Silicon and Intel Macs.",
};

type Detected = { os: OSName; arch: string; confident: boolean };

/**
 * Client-side OS detection. Prefers the high-entropy User-Agent Client
 * Hints (`navigator.userAgentData`) where available, falls back to
 * `navigator.platform` + `navigator.userAgent`. Never blocks render —
 * runs once on mount and only steers the default tab + recommendation.
 */
function detectOS(): Detected {
  if (typeof navigator === "undefined") return { os: "Linux", arch: "x64", confident: false };
  const uaData = (navigator as Navigator & { userAgentData?: { platform?: string } })
    .userAgentData;
  const hinted = (uaData?.platform ?? "").toLowerCase();
  const platform = (navigator.platform ?? "").toLowerCase();
  const ua = (navigator.userAgent ?? "").toLowerCase();
  const src = `${hinted} ${platform} ${ua}`;

  let os: OSName = "Linux";
  if (src.includes("win")) os = "Windows";
  else if (src.includes("mac")) os = "macOS";
  else if (src.includes("linux") || src.includes("x11")) os = "Linux";

  // Architecture matters on macOS (arm vs intel chooser). UA client hints
  // expose it; otherwise "Intel" in the UA means an Intel Mac, and Macs
  // without that marker default to Apple Silicon (the common case now).
  let arch = "x64";
  if (os === "macOS") {
    arch = /intel|macintel/.test(src) ? "x64" : "arm64";
  }

  const confident = hinted !== "" || platform !== "" || ua !== "";
  return { os, arch, confident };
}

function detectedLabel(d: Detected): string {
  if (!d.confident) return "Detection unavailable";
  if (d.os === "macOS") return d.arch === "x64" ? "macOS · Intel" : "macOS · Apple Silicon";
  return `${d.os} · ${d.arch}`;
}

export default function Download() {
  const [selected, setSelected] = useState<OSName>("Linux");
  const [detected, setDetected] = useState<Detected | null>(null);
  const [releaseState, setReleaseState] = useState<"loading" | "available" | "empty" | "error">("loading");
  const [releaseTag, setReleaseTag] = useState<string | null>(null);
  const [releaseUrl, setReleaseUrl] = useState(RELEASES_URL);
  const [releaseAssets, setReleaseAssets] = useState<Partial<Record<ReleaseArtifactId, PublishedReleaseAsset>>>({});
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    const d = detectOS();
    // Mount-only client detection (`navigator` is SSR-absent; render-time
    // reads would hydrate-mismatch) — sync setState on mount is intended.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDetected(d);
    setSelected(d.os);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/releases", { signal: controller.signal })
      .then(async (response) => {
        const body = (await response.json()) as ReleaseLookupResponse;
        if (!response.ok || body.status === "error") {
          throw new Error(body.status === "error" ? body.message : "Release lookup failed");
        }
        if (body.status === "empty") {
          setReleaseState("empty");
          return;
        }
        setReleaseTag(body.release.tag_name);
        setReleaseUrl(body.release.html_url);
        setReleaseAssets(matchReleaseAssets(body.release.assets));
        setReleaseState("available");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setReleaseState("error");
      });
    return () => controller.abort();
  }, []);

  const onTabKeyDown = (e: React.KeyboardEvent, index: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next =
      (index + (e.key === "ArrowRight" ? 1 : OS_TABS.length - 1)) % OS_TABS.length;
    setSelected(OS_TABS[next]);
    tabRefs.current[next]?.focus();
  };

  const cards = RELEASES.filter((a) => a.os === selected);
  const recommendedId =
    selected === "macOS" && detected?.os === "macOS"
      ? detected.arch === "x64"
        ? "macos-intel"
        : "macos-arm"
      : cards.find((c) => c.recommended)?.id ?? cards[0]?.id;

  return (
    <section className="section dl" aria-labelledby="dl-title">
      <div className="wrap">
        {/* OS switcher */}
        <Reveal>
          <div className="dl-switch-row">
            <div
              className="dl-tabs"
              role="group"
              aria-label="Choose your operating system"
            >
              {OS_TABS.map((os, i) => (
                <button
                  key={os}
                  ref={(el) => {
                    tabRefs.current[i] = el;
                  }}
                  type="button"
                  aria-pressed={selected === os}
                  onClick={() => setSelected(os)}
                  onKeyDown={(e) => onTabKeyDown(e, i)}
                  className={`dl-tab${selected === os ? " is-active" : ""}`}
                >
                  {os}
                  {detected?.os === os && (
                    <span className="dl-tab-dot" aria-hidden="true" />
                  )}
                </button>
              ))}
            </div>
            <p className="dl-detected measure" aria-live="polite">
              <span className="dl-detected-label">Detected</span>
              <span className="dl-detected-value">
                {detected ? detectedLabel(detected) : "Detecting…"}
              </span>
            </p>
          </div>
        </Reveal>

        <Reveal>
          <div className="dl-head">
            <h2 id="dl-title" className="display-md">
              {selected} builds
            </h2>
            <p className="body-lead">{OS_BLURB[selected]}</p>
            <p className="dl-release-status measure" aria-live="polite">
              {releaseState === "loading" && "Checking published installers…"}
              {releaseState === "available" && releaseTag && (
                <>
                  Latest desktop release: <a href={releaseUrl} target="_blank" rel="noreferrer">{releaseTag}</a>
                </>
              )}
              {releaseState === "empty" && "No published desktop installers yet."}
              {releaseState === "error" && "Release availability could not be checked."}
            </p>
          </div>
        </Reveal>

        {/* Per-OS cards */}
        <div className="dl-grid">
          {cards.map((a) => {
            const asset = releaseAssets[a.id];
            const live = releaseState === "available" && Boolean(asset);
            const isRec = a.id === recommendedId;
            const availability = releaseState === "loading"
              ? "Checking published release assets"
              : releaseState === "error"
                ? "Could not check GitHub releases"
                : releaseState === "empty"
                  ? "No published installers yet"
                  : asset
                    ? `Available in ${releaseTag}`
                    : "Not included in the latest release";
            return (
              <Reveal key={a.id}>
                <article
                  className={`dl-card${isRec ? " is-rec" : ""}`}
                  aria-label={`${a.title} download`}
                >
                  <div className="dl-card-top">
                    <div>
                      <h3>{a.title}</h3>
                      <p>{a.detail}</p>
                    </div>
                    {isRec && (
                      <span className="dl-rec measure">Recommended</span>
                    )}
                  </div>

                  <dl className="dl-meta measure">
                    <div>
                      <dt>File</dt>
                      <dd>{asset?.name ?? a.filename}</dd>
                    </div>
                    <div>
                      <dt>Arch</dt>
                      <dd>{a.arch}</dd>
                    </div>
                    <div>
                      <dt>Size</dt>
                      <dd>{asset ? formatAssetSize(asset.size) : "Unavailable"}</dd>
                    </div>
                  </dl>

                  <p className="dl-steps-label meta-label">Install</p>
                  <ol className="dl-steps">
                    {a.steps.map((s) => (
                      <li key={s}>{renderStep(s)}</li>
                    ))}
                  </ol>
                  <p className="dl-note">{a.note}</p>

                  <div className="dl-cta">
                    {live ? (
                      <a className="dl-btn" href={asset?.browser_download_url}>
                        Download {a.format}
                      </a>
                    ) : (
                      <a
                        className="dl-btn is-unavailable"
                        href={RELEASES_URL}
                        target="_blank"
                        rel="noreferrer"
                        title={`${availability}. Opens the GitHub releases page.`}
                      >
                        View releases
                      </a>
                    )}
                    <p className="dl-avail measure">
                      {live ? (
                        <>
                          <span className="dl-live-dot" aria-hidden="true" />
                          {availability} ·{" "}
                          <a href={releaseUrl} target="_blank" rel="noreferrer">
                            All releases
                          </a>
                        </>
                      ) : (
                        <>
                          {availability} ·{" "}
                          <a href={RELEASES_URL} target="_blank" rel="noreferrer">
                            GitHub releases
                          </a>
                        </>
                      )}
                    </p>
                  </div>
                </article>
              </Reveal>
            );
          })}
        </div>

        {/* macOS chip chooser hint */}
        {selected === "macOS" && (
          <Reveal>
            <p className="dl-chooser measure">
              Which chip? Apple menu → About This Mac. “Chip” means Apple
              Silicon, “Processor” means Intel.
            </p>
          </Reveal>
        )}

        {/* Source build */}
        <Reveal>
          <div className="dl-source">
            <div>
              <p className="meta-label">From source</p>
              <h3 className="display-md">Or build from source.</h3>
              <p className="body-lead">
                The same tree the installers are built from. Configure a
                release build, compile, then run the test suite.
              </p>
            </div>
            <div className="dl-code">
              <figure>
                <figcaption className="measure">Build</figcaption>
                <pre className="measure">
                  <code>{SOURCE_BUILD.command}</code>
                </pre>
              </figure>
              <figure>
                <figcaption className="measure">Test</figcaption>
                <pre className="measure">
                  <code>{SOURCE_BUILD.test}</code>
                </pre>
              </figure>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/** Render backtick spans as inline code for install commands. */
function renderStep(step: string) {
  const match = step.match(/^(.*?):\s+(.+)$/);
  if (match && /[./-]|sudo|chmod|xattr/.test(match[2])) {
    return (
      <>
        {match[1]}: <code className="measure">{match[2]}</code>
      </>
    );
  }
  return step;
}
