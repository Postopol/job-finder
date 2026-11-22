import {
  createCipheriv,
  createDecipheriv,
  randomBytes,
  scryptSync,
} from "node:crypto";
import fs from "node:fs";
import path from "node:path";

/**
 * AES-256-GCM encryption for secrets at rest (LLM API keys).
 * The key is derived from a random 32-byte file created on first use:
 *   <data>/secret.key  (0600). Delete the file to rotate (keys become
 * unreadable and must be re-entered, which is the safe failure mode).
 */

const KEY_FILE = path.join(
  process.env.DATA_DIR || path.join(process.cwd(), "data"),
  "secret.key",
);

let cachedKey: Buffer | null = null;

function loadMasterKey(): Buffer {
  fs.mkdirSync(path.dirname(KEY_FILE), { recursive: true });
  if (!fs.existsSync(KEY_FILE)) {
    const raw = randomBytes(32);
    fs.writeFileSync(KEY_FILE, raw, { mode: 0o600 });
    return raw;
  }
  return fs.readFileSync(KEY_FILE);
}

export function getMasterKey(): Buffer {
  if (!cachedKey) cachedKey = loadMasterKey();
  return cachedKey;
}

function getKey(): Buffer {
  return scryptSync(getMasterKey(), "resume-studio-key", 32);
}

export function encryptSecret(plaintext: string): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", getKey(), iv);
  const encrypted = Buffer.concat([
    cipher.update(plaintext, "utf8"),
    cipher.final(),
  ]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([iv, tag, encrypted]).toString("base64");
}

export function decryptSecret(payload: string): string | null {
  try {
    const buf = Buffer.from(payload, "base64");
    const iv = buf.subarray(0, 12);
    const tag = buf.subarray(12, 28);
    const data = buf.subarray(28);
    const decipher = createDecipheriv("aes-256-gcm", getKey(), iv);
    decipher.setAuthTag(tag);
    return Buffer.concat([decipher.update(data), decipher.final()]).toString(
      "utf8",
    );
  } catch {
    return null;
  }
}
