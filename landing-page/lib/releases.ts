/**
 * Download manifest — single source of truth for install artifacts.
 *
 * status "coming-soon" renders a disabled card with the reason; no fake URLs.
 * When the `tauri-v*` release workflow publishes artifacts, set status to
 * "available" and fill url/version/size/checksum. Matches the matrix in
 * .github/workflows/release-tauri.yml.
 */

export type ReleaseStatus = "available" | "coming-soon";

export interface ReleaseArtifact {
  id: string;
  os: "Linux" | "Windows" | "macOS";
  title: string;
  detail: string;
  arch: string;
  format: string;
  status: ReleaseStatus;
  reason?: string;
  version?: string;
  url?: string;
  size?: string;
  checksum?: string;
}

export const RELEASES: ReleaseArtifact[] = [
  {
    id: "linux-deb",
    os: "Linux",
    title: "Debian / Ubuntu",
    detail: "For Ubuntu 24.04 and derivatives",
    arch: "x64",
    format: ".deb",
    status: "coming-soon",
    reason: "No tauri-v* release published yet — build from source meanwhile.",
  },
  {
    id: "linux-rpm",
    os: "Linux",
    title: "Fedora / RHEL",
    detail: "For Fedora 44 and derivatives",
    arch: "x64",
    format: ".rpm",
    status: "coming-soon",
    reason: "No tauri-v* release published yet — build from source meanwhile.",
  },
  {
    id: "linux-appimage",
    os: "Linux",
    title: "Universal AppImage",
    detail: "Runs on most modern distributions",
    arch: "x64",
    format: ".AppImage",
    status: "coming-soon",
    reason: "No tauri-v* release published yet — build from source meanwhile.",
  },
  {
    id: "windows-nsis",
    os: "Windows",
    title: "Windows installer",
    detail: "Windows 10 / 11, 64-bit",
    arch: "x64",
    format: ".exe (NSIS)",
    status: "coming-soon",
    reason: "No tauri-v* release published yet — build from source meanwhile.",
  },
  {
    id: "macos-arm",
    os: "macOS",
    title: "Apple Silicon",
    detail: "macOS on ARM64",
    arch: "arm64",
    format: ".dmg",
    status: "coming-soon",
    reason: "No tauri-v* release published yet — build from source meanwhile.",
  },
  {
    id: "macos-intel",
    os: "macOS",
    title: "Intel Mac",
    detail: "macOS on x64",
    arch: "x64",
    format: ".dmg",
    status: "coming-soon",
    reason: "No tauri-v* release published yet — build from source meanwhile.",
  },
];

export const GITHUB_URL = "https://github.com/arjun-713/veyra";

export const SOURCE_BUILD = {
  command: "cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j",
  test: "ctest --test-dir build --output-on-failure",
} as const;
