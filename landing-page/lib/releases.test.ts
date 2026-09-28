import assert from "node:assert/strict";
import test from "node:test";
import { formatAssetSize, matchReleaseAssets } from "./releases.ts";

const assets = [
  { name: "Veyra_0.1.0_amd64.deb", browser_download_url: "https://github.com/arjun-713/veyra/releases/download/v0.1.0/veyra.deb", size: 1048576 },
  { name: "Veyra-0.1.0-1.x86_64.rpm", browser_download_url: "https://github.com/arjun-713/veyra/releases/download/v0.1.0/veyra.rpm", size: 2097152 },
  { name: "Veyra_0.1.0_amd64.AppImage", browser_download_url: "https://github.com/arjun-713/veyra/releases/download/v0.1.0/veyra.AppImage", size: 3145728 },
  { name: "Veyra_0.1.0_x64-setup.exe", browser_download_url: "https://github.com/arjun-713/veyra/releases/download/v0.1.0/veyra.exe", size: 4194304 },
  { name: "Veyra_0.1.0_aarch64.dmg", browser_download_url: "https://github.com/arjun-713/veyra/releases/download/v0.1.0/veyra-arm.dmg", size: 5242880 },
  { name: "Veyra_0.1.0_x64.dmg", browser_download_url: "https://github.com/arjun-713/veyra/releases/download/v0.1.0/veyra-intel.dmg", size: 6291456 },
];

test("matches each supported download card to its real release asset", () => {
  const resolved = matchReleaseAssets(assets);

  assert.deepEqual(Object.keys(resolved).sort(), [
    "linux-appimage", "linux-deb", "linux-rpm", "macos-arm", "macos-intel", "windows-nsis",
  ]);
  assert.equal(resolved["linux-deb"]?.browser_download_url, "https://github.com/arjun-713/veyra/releases/download/v0.1.0/veyra.deb");
  assert.equal(resolved["macos-arm"]?.name, "Veyra_0.1.0_aarch64.dmg");
  assert.equal(resolved["macos-intel"]?.name, "Veyra_0.1.0_x64.dmg");
});

test("matches Tauri output case-insensitively and ignores unrelated assets", () => {
  const resolved = matchReleaseAssets([
    { name: "VEYRA_0.1.0_AMD64.DEB", browser_download_url: "https://github.com/arjun-713/veyra/releases/download/v0.1.0/app.deb", size: 12 },
    { name: "release-manifest.json", browser_download_url: "https://github.com/arjun-713/veyra/releases/download/v0.1.0/manifest", size: 20 },
    { name: "SHA256SUMS", browser_download_url: "https://github.com/arjun-713/veyra/releases/download/v0.1.0/sums", size: 30 },
  ]);

  assert.deepEqual(Object.keys(resolved), ["linux-deb"]);
});

test("does not invent an asset for a platform or architecture that was not published", () => {
  const resolved = matchReleaseAssets([
    { name: "Veyra_0.1.0_amd64.deb", browser_download_url: "https://github.com/arjun-713/veyra/releases/download/v0.1.0/app.deb", size: 12 },
  ]);

  assert.equal(resolved["windows-nsis"], undefined);
  assert.equal(resolved["macos-arm"], undefined);
});

test("formats real byte sizes without showing placeholders", () => {
  assert.equal(formatAssetSize(0), "0 B");
  assert.equal(formatAssetSize(1048576), "1.0 MB");
  assert.equal(formatAssetSize(1073741824), "1.0 GB");
});
