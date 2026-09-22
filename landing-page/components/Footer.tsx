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
            <img src="/veyra-logo.png" alt="Veyra logo" width={64} height={64} />
            <h2 className="display-lg">Map more intelligently.</h2>
            <div className="footer-ctas">
              <a className="btn-download" href="#download">
                Download Veyra
              </a>
              <a className="btn-explore" href={GITHUB_URL} target="_blank" rel="noreferrer">
                GitHub
              </a>
            </div>
          </div>
        </Reveal>
        <div className="footer-base">
          <p className="measure">VEYRA · SIH26053 · ADAPTIVE 2.5D LIDAR MAPPING</p>
          <p>
            Figures are measured on named hardware or labeled analytical.
            Methodology lives in the repository.
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
