/**
 * Download manifest — single source of truth.
 * Pre-release, every card CTA links the GitHub releases page (muted,
 * with an explanatory tooltip); once an artifact's `url` points at a
 * real asset, `isArtifactLive()` flips that card to a direct download.
 * Fine print states release status honestly.
 */

export type OSName = "Linux" | "Windows" | "macOS";

export interface ReleaseArtifact {
  id: string;
  os: OSName;
  title: string;
  detail: string;
  arch: string;
  format: string;
  url: string;
  availability: string;
  /** Filename pattern the tagged release will publish (Tauri bundle naming). */
  filename: string;
  /** Size placeholder shown until binaries ship. */
  size: string;
  /** Install + run steps shown on the card. Rendered in order. */
  steps: string[];
  /** Short caution shown under the steps (gate / SmartScreen / chmod). */
  note: string;
  /** True for the default pick inside its OS tab. */
  recommended?: boolean;
}

export const GITHUB_URL = "https://github.com/arjun-713/veyra";
export const RELEASES_URL = "https://github.com/arjun-713/veyra/releases";

/**
 * True once a tagged release publishes a real asset URL for this artifact.
 * Cards stay honestly disabled while `url` still points at the releases
 * index; flipping `url` to the asset is the only change needed to go live.
 */
export function isArtifactLive(a: ReleaseArtifact): boolean {
  return a.url !== RELEASES_URL;
}

export const RELEASES: ReleaseArtifact[] = [
  {
    id: "linux-deb",
    os: "Linux",
    title: "Debian / Ubuntu",
    detail: "Ubuntu 24.04 and derivatives",
    arch: "x64",
    format: ".deb",
    url: RELEASES_URL,
    availability: "Ships with the first tagged release",
    filename: "veyra_*.amd64.deb",
    size: "Size on first release",
    steps: [
      "Download the .deb for your release tag",
      "Install with: sudo apt install ./veyra_*.amd64.deb",
      "Launch with: veyra",
    ],
    note: "Uses the system package manager — upgrades come with apt.",
    recommended: true,
  },
  {
    id: "linux-rpm",
    os: "Linux",
    title: "Fedora / RHEL",
    detail: "Fedora 44 and derivatives",
    arch: "x64",
    format: ".rpm",
    url: RELEASES_URL,
    availability: "Ships with the first tagged release",
    filename: "veyra-*.x86_64.rpm",
    size: "Size on first release",
    steps: [
      "Download the .rpm for your release tag",
      "Install with: sudo dnf install ./veyra-*.x86_64.rpm",
      "Launch with: veyra",
    ],
    note: "Uses the system package manager — upgrades come with dnf.",
  },
  {
    id: "linux-appimage",
    os: "Linux",
    title: "Portable AppImage",
    detail: "Any distro, no install",
    arch: "x64",
    format: ".AppImage",
    url: RELEASES_URL,
    availability: "Ships with the first tagged release",
    filename: "veyra_*.amd64.AppImage",
    size: "Size on first release",
    steps: [
      "Download the .AppImage for your release tag",
      "Make it executable: chmod +x ./veyra_*.AppImage",
      "Run it: ./veyra_*.AppImage",
    ],
    note: "No root needed. Stays where you put it — good for field laptops.",
  },
  {
    id: "windows-nsis",
    os: "Windows",
    title: "Windows installer",
    detail: "Windows 10 / 11, 64-bit",
    arch: "x64",
    format: ".exe",
    url: RELEASES_URL,
    availability: "Ships with the first tagged release",
    filename: "veyra_*-x64-setup.exe",
    size: "Size on first release",
    steps: [
      "Download the -setup.exe for your release tag",
      "Run it and follow the install wizard",
      "Launch Veyra from the Start menu",
    ],
    note: "First builds are unsigned — SmartScreen may ask for “More info → Run anyway”.",
    recommended: true,
  },
  {
    id: "macos-arm",
    os: "macOS",
    title: "Apple Silicon",
    detail: "macOS on ARM64",
    arch: "arm64",
    format: ".dmg",
    url: RELEASES_URL,
    availability: "Ships with the first tagged release",
    filename: "veyra_*-aarch64.dmg",
    size: "Size on first release",
    steps: [
      "Download the aarch64 .dmg for your release tag",
      "Open it and drag Veyra into Applications",
      "Right-click → Open on first launch",
    ],
    note: "First builds are unsigned — right-click Open (or xattr -d com.apple.quarantine) clears the gate.",
    recommended: true,
  },
  {
    id: "macos-intel",
    os: "macOS",
    title: "Intel Mac",
    detail: "macOS on x64",
    arch: "x64",
    format: ".dmg",
    url: RELEASES_URL,
    availability: "Ships with the first tagged release",
    filename: "veyra_*-x64.dmg",
    size: "Size on first release",
    steps: [
      "Download the x64 .dmg for your release tag",
      "Open it and drag Veyra into Applications",
      "Right-click → Open on first launch",
    ],
    note: "On Apple Silicon Macs pick the ARM64 build instead — Rosetta not required.",
  },
];

export const SOURCE_BUILD = {
  command: "cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j",
  test: "ctest --test-dir build --output-on-failure",
} as const;
