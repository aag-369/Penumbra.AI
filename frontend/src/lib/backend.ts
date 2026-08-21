/**
 * Which backend is this build talking to?
 *
 * With `VITE_API_URL` unset the app runs entirely in the browser against
 * {@link demoBackend}. The encryption is still real -- only storage and
 * transport are local. That is what makes a static Vercel deploy a genuine
 * demonstration rather than a mock-up.
 *
 * With `VITE_API_URL` set, the app probes `/health` and reports what it finds.
 * Note the interop caveat in `docs/SPEC_DEVIATIONS.md` #11: this frontend uses
 * `node-seal` (SEAL-native serialisation) while the Python backend uses TenSEAL
 * (protobuf-wrapped). They are not yet wire-compatible, so a live backend can
 * serve auth and metadata today but cannot yet exchange ciphertexts with this
 * client. The UI states that rather than failing mysteriously.
 */

export type BackendMode = "demo" | "live" | "unreachable";

export interface BackendStatus {
  mode: BackendMode;
  apiUrl: string | null;
  detail: string;
  version?: string;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? null;

export function configuredApiUrl(): string | null {
  return API_URL;
}

export async function probeBackend(): Promise<BackendStatus> {
  if (!API_URL) {
    return {
      mode: "demo",
      apiUrl: null,
      detail:
        "Running standalone. Encryption is real CKKS in this browser; storage is local to this device.",
    };
  }
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 4000);
    const response = await fetch(`${API_URL.replace(/\/api\/v1$/, "")}/health`, {
      signal: controller.signal,
    });
    clearTimeout(timeout);
    if (!response.ok) throw new Error(String(response.status));
    const body = (await response.json()) as { version?: string };
    return {
      mode: "live",
      apiUrl: API_URL,
      version: body.version,
      detail: "Connected to the PENUMBRA API. Ciphertext exchange requires the Phase-6 format shim.",
    };
  } catch {
    return {
      mode: "unreachable",
      apiUrl: API_URL,
      detail: `Could not reach ${API_URL}. Falling back to in-browser storage; encryption is unaffected.`,
    };
  }
}
