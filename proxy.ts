import { NextRequest, NextResponse } from "next/server";
import { isLoopbackHost, isLoopbackOrigin } from "@/lib/local-only";

/**
 * Local-only guard for the API and the print route.
 *
 * - Host must be this computer: blocks other machines on the network and DNS rebinding
 *   (a site that re-points its own domain to 127.0.0.1).
 * - State-changing requests from a browser must come from Resume Studio's own pages:
 *   a foreign Origin, or Sec-Fetch-Site "cross-site", is refused (CSRF). Requests without
 *   these headers (curl, Job Finder server-to-server) pass.
 */

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

function forbidden(reason: string): NextResponse {
  return NextResponse.json({ error: `Forbidden: ${reason}` }, { status: 403 });
}

export function proxy(request: NextRequest) {
  if (!isLoopbackHost(request.headers.get("host"))) {
    return forbidden("Resume Studio only accepts requests from this computer.");
  }
  if (!SAFE_METHODS.has(request.method)) {
    const origin = request.headers.get("origin");
    if (origin && !isLoopbackOrigin(origin)) {
      return forbidden("cross-site request.");
    }
    if (request.headers.get("sec-fetch-site") === "cross-site") {
      return forbidden("cross-site request.");
    }
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/api/:path*", "/print/:path*"],
};
