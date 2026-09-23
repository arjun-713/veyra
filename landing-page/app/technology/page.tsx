import type { Metadata } from "next";
import Nav from "../../components/Nav";
import Footer from "../../components/Footer";
import PageHead from "../../components/ui/PageHead";
import Pipeline from "../../components/technology/Pipeline";
import Explainer from "../../components/sections/Explainer";
import Resolution from "../../components/sections/Resolution";

export const metadata: Metadata = {
  title: "Technology — Veyra adaptive 2.5D mapping",
  description:
    "How Veyra works: raw LiDAR to semantic perception, terrain and motion, adaptive 2.5D cells at 5–40 cm, range-binned quality.",
};

export default function TechnologyPage() {
  return (
    <>
      <Nav />
      <main id="main">
        <PageHead
          trail="Technology"
          title="How Veyra maps."
          lede="Raw LiDAR becomes semantic understanding, then an adaptive 2.5D map that spends resolution where losing it costs something."
        />
        <Pipeline />
        <Explainer />
        <Resolution />
      </main>
      <Footer />
    </>
  );
}
