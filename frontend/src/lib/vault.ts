/**
 * Passphrase-sealed local storage for the CKKS secret key.
 *
 * PBKDF2-SHA256 to derive an AES-256-GCM key, both from WebCrypto. The server
 * uses scrypt for the same job; browsers do not expose scrypt, and PBKDF2 at
 * 310,000 iterations is the closest defensible equivalent -- it is the figure
 * OWASP recommends for PBKDF2-HMAC-SHA256.
 *
 * GCM rather than CBC so a tampered blob fails to open instead of decrypting to
 * garbage. A user restoring a corrupted backup gets an error, not a portfolio
 * full of nonsense.
 *
 * Only the *secret key* is stored -- roughly 0.3 MB. The public, relinearisation
 * and rotation keys are regenerated from it on restore, which is necessary
 * because rotation keys alone are ~45 MB and would blow the storage quota many
 * times over.
 */

const PBKDF2_ITERATIONS = 310_000;
const SALT_BYTES = 16;
const NONCE_BYTES = 12;
const VERSION = 1;

export class VaultError extends Error {}

const STORAGE_KEY = "penumbra.vault.v1";

function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  // Chunked: String.fromCharCode(...bytes) blows the call stack past ~100 kB,
  // and a sealed secret key is around 400 kB.
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

function fromBase64(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function deriveKey(passphrase: string, salt: Uint8Array): Promise<CryptoKey> {
  const material = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(passphrase),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: salt as BufferSource, iterations: PBKDF2_ITERATIONS, hash: "SHA-256" },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

export interface VaultPayload {
  keyId: string;
  secretKey: string;
  polyModulusDegree: number;
  coeffModBitSizes: number[];
  scaleBits: number;
  createdAt: string;
}

export async function seal(payload: VaultPayload, passphrase: string): Promise<string> {
  if (!passphrase) throw new VaultError("passphrase must not be empty");
  const salt = crypto.getRandomValues(new Uint8Array(SALT_BYTES));
  const nonce = crypto.getRandomValues(new Uint8Array(NONCE_BYTES));
  const key = await deriveKey(passphrase, salt);
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: nonce as BufferSource },
    key,
    new TextEncoder().encode(JSON.stringify(payload)),
  );
  return JSON.stringify({
    v: VERSION,
    salt: toBase64(salt.buffer as ArrayBuffer),
    nonce: toBase64(nonce.buffer as ArrayBuffer),
    ct: toBase64(ciphertext),
  });
}

export async function unseal(blob: string, passphrase: string): Promise<VaultPayload> {
  let envelope: { v?: number; salt?: string; nonce?: string; ct?: string };
  try {
    envelope = JSON.parse(blob);
  } catch {
    throw new VaultError("sealed key is malformed");
  }
  if (envelope.v !== VERSION) throw new VaultError(`unsupported vault version ${envelope.v}`);
  if (!envelope.salt || !envelope.nonce || !envelope.ct) throw new VaultError("sealed key is malformed");

  const key = await deriveKey(passphrase, fromBase64(envelope.salt));
  try {
    const plaintext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: fromBase64(envelope.nonce) as BufferSource },
      key,
      fromBase64(envelope.ct) as BufferSource,
    );
    return JSON.parse(new TextDecoder().decode(plaintext)) as VaultPayload;
  } catch {
    throw new VaultError("wrong passphrase, or the sealed key has been tampered with");
  }
}

export function storeSealed(blob: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, blob);
  } catch {
    throw new VaultError(
      "could not write the sealed key to browser storage -- it may be full or blocked in private browsing",
    );
  }
}

export function readSealed(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function clearSealed(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage blocked; nothing to clear */
  }
}

/** Problems with a passphrase, or an empty list if it is acceptable. */
export function passphraseProblems(passphrase: string): string[] {
  const problems: string[] = [];
  if (passphrase.length < 12) problems.push("at least 12 characters");
  if (!/[a-zA-Z]/.test(passphrase)) problems.push("at least one letter");
  if (!/[0-9]/.test(passphrase)) problems.push("at least one digit");
  return problems;
}
