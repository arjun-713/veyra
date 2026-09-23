"use client";

import { useEffect, useState } from "react";
import "./Nav.css";
import { GITHUB_URL } from "../lib/releases";

const LINKS = [
  { href: "/technology", label: "Technology" },
  { href: "/evidence", label: "Evidence" },
  { href: "/app", label: "App" },
  { href: "/download", label: "Download" },
];

export default function Nav() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <nav className={`nav${scrolled ? " is-scrolled" : ""}`} aria-label="Primary">
      <div className="nav-inner">
        <a className="nav-brand" href="/" aria-label="Veyra home">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/veyra-logo.png" alt="" width={30} height={30} />
          <span>VEYRA</span>
        </a>
        <div className="nav-links">
          {LINKS.map((link) => (
            <a key={link.href} href={link.href}>
              {link.label}
            </a>
          ))}
          <a className="nav-cta" href={GITHUB_URL} target="_blank" rel="noreferrer">
            GitHub
          </a>
        </div>
      </div>
    </nav>
  );
}
