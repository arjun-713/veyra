import type { Metadata, Viewport } from "next";
import "@fontsource/space-grotesk/400.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/600.css";
import "@fontsource/space-grotesk/700.css";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import "../styles/tokens.css";
import "../styles/typography.css";
import "../styles/globals.css";

export const metadata: Metadata = {
  title: "Veyra — Adaptive Semantic 2.5D LiDAR Mapping",
  description:
    "Veyra compresses sequential 3D LiDAR into a semantic, variable-resolution 2.5D map — fine detail where it matters, coarse elsewhere. Measured memory, latency, and quality evidence.",
  metadataBase: new URL("https://github.com/arjun-713/veyra"),
  openGraph: {
    title: "Veyra — Adaptive Semantic 2.5D LiDAR Mapping",
    description:
      "Robot-centric adaptive-resolution 2.5D mapping from raw LiDAR. 5–40 cm cells, measured evidence, open source.",
    type: "website",
    images: [{ url: "/veyra-logo.png", width: 540, height: 540, alt: "Veyra logo" }],
  },
  twitter: {
    card: "summary",
    title: "Veyra — Adaptive Semantic 2.5D LiDAR Mapping",
    description:
      "Semantic 2.5D LiDAR mapping with adaptive 5–40 cm resolution. Measured, not marketed.",
  },
  icons: { icon: "/veyra-logo.png", apple: "/veyra-logo.png" },
};

export const viewport: Viewport = {
  themeColor: "#070c12",
  width: "device-width",
  initialScale: 1,
};

/** Emits the direction contract as a real HTML comment (JSX comments strip). */
function DirectionContract() {
  const contract = `DIRECTION CONTRACT — Veyra landing (Persuade, established world).
THESIS: the mapper that spends resolution where losing info matters; refuses the SaaS-hero template and the purple-AI gradient.
OWN-WORLD: bright light instrument, near-white ground, hairline borders, tabular mono instrumentation, teal signal, Space Grotesk display / Inter UI / Plex Mono measure.
STORY: visitor sees LiDAR become an adaptive 2.5D map in the hero, reads measured evidence, downloads or builds.
FIRST VIEWPORT: left HTML headline + CTAs + annotations; right live LiDAR sweep crystallizing into L0-L3 cells around a UGV.
FORM: cinematic instrument panel; seed: veyra-ops-01.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and DESIGN.md.`;
  return <div dangerouslySetInnerHTML={{ __html: `<!--${contract}-->` }} />;
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <DirectionContract />
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
