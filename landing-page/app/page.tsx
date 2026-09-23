import type { Metadata } from "next";
import Nav from "../components/Nav";
import Hero from "../components/hero/Hero";
import Problem from "../components/sections/Problem";
import Pipeline from "../components/technology/Pipeline";
import Showcase from "../components/screenshots/Showcase";
import Footer from "../components/Footer";
import { ResolutionTeaser, EvidenceHighlights, DownloadCta } from "../components/home/teasers";

export default function Page() {
  return (
    <>
      <Nav />
      <main id="main">
        <Hero />
        <Problem />
        <Pipeline />
        <ResolutionTeaser />
        <EvidenceHighlights />
        <Showcase limit={2} moreHref="/app" />
        <DownloadCta />
      </main>
      <Footer />
    </>
  );
}
