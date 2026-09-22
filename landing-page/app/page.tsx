import Nav from "../components/Nav";
import Hero from "../components/Hero";
import Problem from "../components/sections/Problem";
import Pipeline from "../components/sections/Pipeline";
import Explainer from "../components/sections/Explainer";
import Resolution from "../components/sections/Resolution";
import Evidence from "../components/sections/Evidence";
import Showcase from "../components/sections/Showcase";
import Download from "../components/sections/Download";
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
        <Showcase />
        <Download />
        <Engineering />
      </main>
      <Footer />
    </>
  );
}
