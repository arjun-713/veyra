import Nav from "../components/Nav";
import Hero from "../components/hero/Hero";
import Problem from "../components/sections/Problem";
import Pipeline from "../components/technology/Pipeline";
import Explainer from "../components/sections/Explainer";
import Resolution from "../components/sections/Resolution";
import Evidence from "../components/evidence/Evidence";
import RangeQuality from "../components/evidence/RangeQuality";
import Showcase from "../components/screenshots/Showcase";
import Download from "../components/downloads/Download";
import Engineering from "../components/sections/Engineering";
import Footer from "../components/Footer";

export default function Page() {
  return (
    <>
      <Nav />
      <main id="main">
        <Hero />
        <Problem />
        <Pipeline />
        <Explainer />
        <Resolution />
        <Evidence />
        <RangeQuality />
        <Showcase />
        <Download />
        <Engineering />
      </main>
      <Footer />
    </>
  );
}
