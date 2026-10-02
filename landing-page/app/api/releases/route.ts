import { NextResponse } from "next/server";
import {
  parsePublishedRelease,
  type ReleaseLookupResponse,
} from "../../../lib/releases";

export const revalidate = 300;

const GITHUB_RELEASES_API = "https://api.github.com/repos/arjun-713/veyra/releases/latest";
const CACHE_HEADERS = { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=600" };

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
    if (response.status === 404) {
      return NextResponse.json({ status:"empty" }, { headers:CACHE_HEADERS });
    }
    if (!response.ok) {
      const body: ReleaseLookupResponse = {
        status: "error",
        message: "GitHub releases could not be checked right now.",
      };
      return NextResponse.json(body, { status: 502, headers: { "Cache-Control": "no-store" } });
    }

    const body = parsePublishedRelease(await response.json());
    return NextResponse.json(body, { headers:CACHE_HEADERS });
  } catch {
    const body: ReleaseLookupResponse = {
      status: "error",
      message: "GitHub releases could not be checked right now.",
    };
    return NextResponse.json(body, { status: 502, headers: { "Cache-Control": "no-store" } });
  }
}
