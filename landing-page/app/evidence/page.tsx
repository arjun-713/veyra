import type { Metadata } from "next";
import Nav from "../../components/Nav";
import Footer from "../../components/Footer";
import PageHead from "../../components/ui/PageHead";
import Evidence from "../../components/evidence/Evidence";
import RangeQuality from "../../components/evidence/RangeQuality";

export const metadata: Metadata = {
  title: "Evidence — Veyra measured benchmarks",
  description:
    "Measured DistanceLOD vs Uniform5 evidence with provenance: memory, cells, latency, RMSE, coverage and retention. Analytical kept separate.",
};

export default function EvidencePage() {
  return (
    <>
      <Nav />
      <main id="main">
        <PageHead
          trail="Evidence"
          title="Measured, in full."
          lede="Every value below ran on identical frames and identical hardware. Analytical estimates stay labeled; unavailable stays N/A."
        />
        <Evidence />
        <RangeQuality />
      </main>
      <Footer />
    </>
  );
}
