/**
 * Resume Studio is a single-user local app: only this computer may talk to it.
 * Used by proxy.ts (every API/print request) and the PDF route (print origin).
 */

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);

/** "127.0.0.1:3000" / "localhost" / "[::1]:3000" → true; "evil.example", "192.168.1.5:3000" → false. */
export function isLoopbackHost(host: string | null | undefined): boolean {
  if (!host) return false;
  const value = host.trim().toLowerCase();
  const name = value.startsWith("[")
    ? value.slice(0, value.indexOf("]") + 1)
    : value.replace(/:\d+$/, "");
  return LOOPBACK_HOSTS.has(name);
}
