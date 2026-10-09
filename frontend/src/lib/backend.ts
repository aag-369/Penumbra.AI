/**
 * Which backend is this build talking to?
 *
 * Resolution order:
 *
 * 1. `VITE_API_URL`, if set at build time.
 * 2. Otherwise, when the page itself is served from this machine (`localhost`
 *    or `127.0.0.1`), the API on port 8000 of the same host -- so running the
 *    two locally connects them with no configuration.
 * 3. Otherwise none: the app runs entirely in the browser against
 *    {@link demoBackend}. The encryption is still real -- only storage and
 *    transport are local. That is what makes a static Vercel deploy a genuine
 *    demonstration rather than a mock-up.
 *
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
  /** Where `apiUrl` came from: set explicitly, found on this machine, or neither. */
  source: "configured" | "local" | "none";
  detail: string;
  version?: string;
  latencyMs?: number;
  checkedAt: number;
}

const CONFIGURED = (import.meta.env.VITE_API_URL as string | undefined)?.trim().replace(/\/$/, "") || null;
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);
const HEALTH_TIMEOUT_MS = 5000;

function localApiUrl(): string | null {
  if (typeof window === "undefined") return null;
  const { hostname } = window.location;
  return LOCAL_HOSTS.has(hostname) ? `http://${hostname}:8000/api/v1` : null;
}

export function configuredApiUrl(): string | null {
  return CONFIGURED ?? localApiUrl();
}

/** `http://host:8000/api/v1` -> `http://host:8000`, where `/health` and `/docs` live. */
export function apiOrigin(apiUrl: string): string {
  return apiUrl.replace(/\/api\/v1$/, "");
}

export async function probeBackend(): Promise<BackendStatus> {
  const apiUrl = configuredApiUrl();
  const source: BackendStatus["source"] = CONFIGURED ? "configured" : apiUrl ? "local" : "none";
  const checkedAt = Date.now();

  if (!apiUrl) {
    return {
      mode: "demo",
      apiUrl: null,
      source,
      checkedAt,
      detail: "Running standalone. Encryption is real CKKS in this browser; storage is local to this device.",
    };
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
  const started = performance.now();
  try {
    const response = await fetch(`${apiOrigin(apiUrl)}/health`, {
      signal: controller.signal,
      cache: "no-store",
    });
    if (!response.ok) throw new Error(String(response.status));
    const body = (await response.json()) as { version?: string };
    return {
      mode: "live",
      apiUrl,
      source,
      checkedAt,
      version: body.version,
      latencyMs: performance.now() - started,
      detail: "Connected to the PENUMBRA API. Ciphertext exchange requires the Phase-6 format shim.",
    };
  } catch {
    // An API we were told about and cannot reach is a fault worth showing. One
    // we merely looked for on this machine is not -- that is standalone mode.
    return source === "configured"
      ? {
          mode: "unreachable",
          apiUrl,
          source,
          checkedAt,
          detail: `Could not reach ${apiUrl}. Falling back to in-browser storage; encryption is unaffected.`,
        }
      : {
          mode: "demo",
          apiUrl,
          source,
          checkedAt,
          detail:
            "No API found on port 8000, so the app runs standalone. Encryption is real CKKS in this browser.",
        };
  } finally {
    clearTimeout(timeout);
  }
}
