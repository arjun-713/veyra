import type { Metadata } from "next";
import Nav from "../../components/Nav";
import Footer from "../../components/Footer";
import PageHead from "../../components/ui/PageHead";
import Download from "../../components/download/Download";

export const metadata: Metadata = {
  title: "Download — Veyra for Windows, macOS and Linux",
  description:
    "Get Veyra for Windows, macOS and Linux, or build from source with CMake.",
};

export default function DownloadPage() {
  return (
    <>
      <Nav />
      <main id="main">
        <PageHead
          trail="Download"
          title="Run it on your machine."
          lede="Check published installers for Linux, Windows, or macOS, or build Veyra from source."
        />
        <Download />
      </main>
      <Footer />
    </>
  );
}
