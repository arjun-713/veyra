import { NextResponse } from "next/server";
import {
  matchReleaseAssets,
  type PublishedReleaseAsset,
  type ReleaseLookupResponse,
} from "../../../lib/releases";

export const revalidate = 300;

const GITHUB_RELEASES_API = "https://api.github.com/repos/arjun-713/veyra/releases?per_page=10";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseAsset(value: unknown): PublishedReleaseAsset | null {
  if (!isRecord(value)) return null;
  const { name, browser_download_url: url, size } = value;
  if (
    typeof name !== "string" ||
    typeof url !== "string" ||
    !url.startsWith("https://github.com/") ||
    typeof size !== "number" ||
    !Number.isFinite(size) ||
    size < 0
  ) {
    return null;
  }
  return { name, browser_download_url: url, size };
}

export async function GET() {
  try {
    const response = await fetch(GITHUB_RELEASES_API, {
      headers: {
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      next: { revalidate },
      signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) {
      const body: ReleaseLookupResponse = {
        status: "error",
        message: "GitHub releases could not be checked right now.",
      };
      return NextResponse.json(body, { status: 502, headers: { "Cache-Control": "no-store" } });
    }

    const payload: unknown = await response.json();
    if (!Array.isArray(payload)) throw new Error("GitHub returned an invalid release list.");
    for (const item of payload) {
      if (!isRecord(item) || item.draft === true || typeof item.tag_name !== "string") continue;
      if (typeof item.html_url !== "string" || !item.html_url.startsWith("https://github.com/")) continue;
      const rawAssets = Array.isArray(item.assets) ? item.assets : [];
      const assets = rawAssets.map(parseAsset).filter((asset): asset is PublishedReleaseAsset => asset !== null);
      const supported = matchReleaseAssets(assets);
      if (Object.keys(supported).length === 0) continue;
      const body: ReleaseLookupResponse = {
        status: "available",
        release: {
          tag_name: item.tag_name,
          html_url: item.html_url,
          assets: Object.values(supported),
        },
      };
      return NextResponse.json(body, { headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=600" } });
    }

    const body: ReleaseLookupResponse = { status: "empty" };
    return NextResponse.json(body, { headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=600" } });
  } catch {
    const body: ReleaseLookupResponse = {
      status: "error",
      message: "GitHub releases could not be checked right now.",
    };
    return NextResponse.json(body, { status: 502, headers: { "Cache-Control": "no-store" } });
  }
}
