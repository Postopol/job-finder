import { createHmac, timingSafeEqual } from "node:crypto";
import { getMasterKey } from "./crypto";

/**
 * Stateless print tokens: HMAC(resumeId, expiry) signed with the local
 * secret key. Works across processes (route handler issues, print page
 * verifies) with no shared memory and no DB round-trip.
 */

const TTL_MS = 60_000;

function hmac(payload: string): string {
  return createHmac("sha256", getMasterKey()).update(payload).digest("base64url");
}

export function issuePrintToken(resumeId: string): string {
  const expiresAt = Date.now() + TTL_MS;
  const payload = `${resumeId}.${expiresAt}`;
  return `${payload}.${hmac(payload)}`;
}

export function verifyPrintToken(token: string, resumeId: string): boolean {
  const parts = token.split(".");
  if (parts.length !== 3) return false;
  const [id, expiresAtRaw, signature] = parts;
  const expiresAt = Number(expiresAtRaw);
  if (!Number.isFinite(expiresAt) || expiresAt < Date.now()) return false;
  const expected = hmac(`${id}.${expiresAtRaw}`);
  const a = Buffer.from(signature);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !timingSafeEqual(a, b)) return false;
  return id === resumeId;
}
