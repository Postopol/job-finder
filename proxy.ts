import { NextRequest, NextResponse } from "next/server";
import { isLoopbackHost } from "@/lib/local-only";

/**
 * Local-only guard for the API and the print route.
 *
 * - Host must be this computer: blocks other machines on the network and DNS rebinding
 *   (a site that re-points its own domain to 127.0.0.1).
 * - State-changing requests from a browser must come from Resume Studio's own pages: the
 *   Origin must be exactly this host and port (another local app on another port is a
 *   different site), and Sec-Fetch-Site, when sent, must be "same-origin" or "none" (CSRF).
 *   Requests without these headers (curl, Job Finder server-to-server) pass.
 */

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const ALLOWED_FETCH_SITES = new Set(["same-origin", "none"]);

function sameOrigin(origin: string, host: string | null): boolean {
  try {
    return new URL(origin).host === (host ?? "").toLowerCase();
  } catch {
    return false;
  }
}

function forbidden(reason: string): NextResponse {
  return NextResponse.json({ error: `Forbidden: ${reason}` }, { status: 403 });
}

export function proxy(request: NextRequest) {
  if (!isLoopbackHost(request.headers.get("host"))) {
    return forbidden("Resume Studio only accepts requests from this computer.");
  }
  if (!SAFE_METHODS.has(request.method)) {
    const origin = request.headers.get("origin");
    if (origin && !sameOrigin(origin, request.headers.get("host"))) {
      return forbidden("cross-site request.");
    }
    const fetchSite = request.headers.get("sec-fetch-site");
    if (fetchSite && !ALLOWED_FETCH_SITES.has(fetchSite)) {
      return forbidden("cross-site request.");
    }
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/api/:path*", "/print/:path*"],
};
