/**
 * Download-card metadata. Availability and URLs are resolved from the
 * public GitHub Releases API; this file never claims an asset exists.
 */

export type OSName = "Linux" | "Windows" | "macOS";
export type ReleaseArtifactId =
  | "linux-deb"
  | "linux-rpm"
  | "linux-appimage"
  | "windows-nsis"
  | "macos-arm"
  | "macos-intel";

export interface ReleaseArtifact {
  id: ReleaseArtifactId;
  os: OSName;
  title: string;
  detail: string;
  arch: string;
  format: string;
  /** Expected Tauri filename, shown only while no matching asset is published. */
  filename: string;
  /** Install + run steps shown on the card. Rendered in order. */
  steps: string[];
  /** Short caution shown under the steps (gate / SmartScreen / chmod). */
  note: string;
  /** True for the default pick inside its OS tab. */
  recommended?: boolean;
}

export interface PublishedReleaseAsset {
  name: string;
  browser_download_url: string;
  size: number;
}

export type ReleaseLookupResponse =
  | {
      status: "available";
      release: { tag_name: string; html_url: string; assets: PublishedReleaseAsset[] };
    }
  | { status: "empty" }
  | { status: "error"; message: string };

const ASSET_MATCHERS: Record<ReleaseArtifactId, RegExp> = {
  "linux-deb": /^veyra.*_(amd64|x86_64)\.deb$/i,
  "linux-rpm": /^veyra.*\.(x86_64|amd64)\.rpm$/i,
  "linux-appimage": /^veyra.*_(amd64|x86_64)\.appimage$/i,
  "windows-nsis": /^veyra.*[_-]x64-setup\.exe$/i,
  "macos-arm": /^veyra.*_(aarch64|arm64)\.dmg$/i,
  "macos-intel": /^veyra.*_(x64|x86_64)\.dmg$/i,
};

/** Match only native installers whose Tauri filename identifies the card's OS/architecture. */
export function matchReleaseAssets(
  assets: PublishedReleaseAsset[],
): Partial<Record<ReleaseArtifactId, PublishedReleaseAsset>> {
  const matches: Partial<Record<ReleaseArtifactId, PublishedReleaseAsset>> = {};
  for (const artifact of RELEASES) {
    const matcher = ASSET_MATCHERS[artifact.id];
    const asset = assets.find(
      (candidate) =>
        matcher.test(candidate.name) &&
        candidate.browser_download_url.startsWith("https://github.com/") &&
        Number.isFinite(candidate.size) &&
        candidate.size >= 0,
    );
    if (asset) matches[artifact.id] = asset;
  }
  return matches;
}

/** Validate the GitHub /releases/latest response before enabling downloads. */
export function parsePublishedRelease(value: unknown): ReleaseLookupResponse {
  if (typeof value !== "object" || value === null) return { status:"empty" };
  const item = value as Record<string, unknown>;
  if (
    item.draft !== false || item.prerelease !== false ||
    typeof item.tag_name !== "string" || !item.tag_name ||
    typeof item.html_url !== "string" || !item.html_url.startsWith(`${RELEASES_URL}/tag/`) ||
    !Array.isArray(item.assets)
  ) return { status:"empty" };
  const releaseAssetPrefix = `${RELEASES_URL}/download/${encodeURIComponent(item.tag_name)}/`;
  const assets: PublishedReleaseAsset[] = [];
  for (const raw of item.assets) {
    if (typeof raw !== "object" || raw === null) continue;
    const asset = raw as Record<string, unknown>;
    if (
      typeof asset.name === "string" &&
      typeof asset.browser_download_url === "string" &&
      asset.browser_download_url.startsWith(releaseAssetPrefix) &&
      typeof asset.size === "number" && Number.isFinite(asset.size) && asset.size > 0
    ) assets.push({name:asset.name, browser_download_url:asset.browser_download_url, size:asset.size});
  }
  const matched = Object.values(matchReleaseAssets(assets));
  // Publish is all-or-nothing: never combine installers from different versions.
  if (matched.length !== RELEASES.length) return { status:"empty" };
  return { status:"available", release:{tag_name:item.tag_name, html_url:item.html_url, assets:matched} };
}

export function formatAssetSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = -1;
  do {
    value /= 1024;
    unit += 1;
  } while (value >= 1024 && unit < units.length - 1);
  return `${value.toFixed(1)} ${units[unit]}`;
}

export const GITHUB_URL = "https://github.com/arjun-713/veyra";
export const RELEASES_URL = "https://github.com/arjun-713/veyra/releases";

export const RELEASES: ReleaseArtifact[] = [
  {
    id: "linux-deb",
    os: "Linux",
    title: "Debian / Ubuntu",
    detail: "Ubuntu 24.04 and derivatives",
    arch: "x64",
    format: ".deb",
    filename: "Veyra_*_amd64.deb",
    steps: [
      "Download the .deb for your release tag",
      "Install with: sudo apt install ./Veyra_*_amd64.deb",
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
    filename: "Veyra-*.x86_64.rpm",
    steps: [
      "Download the .rpm for your release tag",
      "Install with: sudo dnf install ./Veyra-*.x86_64.rpm",
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
    filename: "Veyra_*_amd64.AppImage",
    steps: [
      "Download the .AppImage for your release tag",
      "Make it executable: chmod +x ./Veyra_*_amd64.AppImage",
      "Run it: ./Veyra_*_amd64.AppImage",
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
    filename: "Veyra_*_x64-setup.exe",
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
    filename: "Veyra_*_aarch64.dmg",
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
    filename: "Veyra_*_x64.dmg",
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
