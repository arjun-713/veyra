import Reveal from "./ui/Reveal";
import { GITHUB_URL } from "../lib/releases";
import "./Footer.css";

export default function Footer() {
  return (
    <footer className="footer">
      <div className="wrap footer-inner">
        <Reveal>
          <div className="footer-close">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/veyra-logo.png" alt="Veyra logo" width={56} height={56} />
            <h2>Map only what matters.</h2>
            <p>Adaptive semantic 2.5D LiDAR mapping — measured, bounded, open.</p>
            <div className="footer-ctas">
              <a className="btn-primary" href="#download">
                Download Veyra
              </a>
              <a className="btn-ghost" href={GITHUB_URL} target="_blank" rel="noreferrer">
                View on GitHub
              </a>
            </div>
          </div>
        </Reveal>
        <div className="footer-base">
          <p className="tnum">VEYRA · SIH26053 · ADAPTIVE 2.5D LIDAR MAPPING</p>
          <p>
            Benchmark figures on this page are measured on named hardware or labeled
            analytical. Full methodology lives in the repository.
          </p>
          <p>
            <a href={GITHUB_URL} target="_blank" rel="noreferrer">
              github.com/arjun-713/veyra
            </a>
          </p>
        </div>
      </div>
    </footer>
  );
}
