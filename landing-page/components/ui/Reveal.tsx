"use client";

import { useEffect, useRef, type ReactNode } from "react";

interface RevealProps {
  children: ReactNode;
  as?: "div" | "section" | "li" | "figure";
  className?: string;
  delayMs?: number;
}

/** IntersectionObserver reveal; content is visible without JS motion. */
export default function Reveal({ children, as = "div", className = "", delayMs = 0 }: RevealProps) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in");
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const Tag = as as "div";
  return (
    <Tag ref={ref} className={`reveal${className ? ` ${className}` : ""}`} style={{ transitionDelay: `${delayMs}ms` }}>
      {children}
    </Tag>
  );
}
