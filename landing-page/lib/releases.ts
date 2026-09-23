/**
 * Download manifest — single source of truth.
 * Cards link to the GitHub releases page, the production destination for
 * packaged artifacts. Fine print states release status honestly.
 */

export interface ReleaseArtifact {
  id: string;
  os: "Linux" | "Windows" | "macOS";
  title: string;
  detail: string;
  arch: string;
  format: string;
  url: string;
  availability: string;
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
    url: RELEASES_URL,
    availability: "Ships with the first tagged release",
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
  },
];

export const SOURCE_BUILD = {
  command: "cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j",
  test: "ctest --test-dir build --output-on-failure",
} as const;
