import type { Metadata } from "next";
import Nav from "../../components/Nav";
import Footer from "../../components/Footer";
import PageHead from "../../components/ui/PageHead";
import Showcase from "../../components/screenshots/Showcase";

export const metadata: Metadata = {
  title: "App — Veyra operator views",
  description:
    "The Veyra desktop app: live mapping, performance, benchmark comparison and validation views.",
};

export default function AppPage() {
  return (
    <>
      <Nav />
      <main id="main">
        <PageHead
          trail="App"
          title="Proof, not logs."
          lede="Map, resolution distribution, telemetry and benchmark comparison side by side in the operator app."
        />
        <Showcase />
      </main>
      <Footer />
    </>
  );
}
