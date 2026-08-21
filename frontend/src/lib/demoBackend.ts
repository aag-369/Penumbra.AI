/**
 * An in-browser stand-in for the PENUMBRA API.
 *
 * What it replaces: storage and transport. What it does **not** replace: the
 * cryptography. Ciphertexts handed to this module are produced by real CKKS in
 * `seal.ts`, and this module is exactly as unable to read them as the Python
 * server is -- it never sees a secret key either. So the privacy property the
 * project is about is demonstrated honestly even with no backend running.
 *
 * State lives in `localStorage`, minus the ciphertexts, which are held in memory
 * for the session. A CKKS ciphertext is ~440 kB and the storage quota is a few
 * megabytes, so persisting them would fail on the third portfolio.
 */

import type {
  AdvisoryJobRecord,
  AuditRecord,
  EncryptionKeyRecord,
  EncryptionStats,
  PortfolioRecord,
  SystemHealth,
  User,
} from "./types";

const STORE_KEY = "penumbra.demo.v1";
const BOOT_TIME = Date.now();

interface DemoState {
  users: (User & { password: string })[];
  keys: EncryptionKeyRecord[];
  portfolios: Omit<PortfolioRecord, "holdings_ciphertext" | "cost_basis_ciphertext">[];
  jobs: AdvisoryJobRecord[];
  audit: AuditRecord[];
  session: string | null;
}

/** Ciphertexts, held in memory only -- far too large for localStorage. */
const ciphertexts = new Map<string, { holdings: string; costBasis: string | null }>();
const recommendations = new Map<string, string>();

function emptyState(): DemoState {
  return { users: [], keys: [], portfolios: [], jobs: [], audit: [], session: null };
}

function load(): DemoState {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    return raw ? { ...emptyState(), ...(JSON.parse(raw) as DemoState) } : emptyState();
  } catch {
    return emptyState();
  }
}

function save(state: DemoState): void {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(state));
  } catch {
    /* quota or private browsing; the session still works in memory */
  }
}

let state = load();

function uuid(): string {
  return crypto.randomUUID();
}

function now(): string {
  return new Date().toISOString();
}

function audit(
  action: string,
  severity: AuditRecord["severity"] = "info",
  details: Record<string, unknown> = {},
  resourceType: string | null = null,
): void {
  state.audit.unshift({
    id: uuid(),
    action,
    severity,
    actor_user_id: state.session,
    resource_type: resourceType,
    details,
    created_at: now(),
  });
  state.audit = state.audit.slice(0, 300);
  save(state);
}

export class DemoError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

function currentUser(): User {
  const user = state.users.find((u) => u.id === state.session);
  if (!user) throw new DemoError("invalid_token", "not signed in");
  return user;
}

/** Small delay so loading states are visible rather than flashing. */
function settle<T>(value: T, delay = 180): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), delay));
}

export const demoBackend = {
  isDemo: true,

  reset(): void {
    state = emptyState();
    ciphertexts.clear();
    recommendations.clear();
    save(state);
  },

  async register(email: string, password: string): Promise<User> {
    const normalised = email.trim().toLowerCase();
    if (state.users.some((u) => u.email === normalised)) {
      throw new DemoError("invalid_credentials", "that email cannot be registered");
    }
    if (password.length < 12) {
      throw new DemoError("request_invalid", "password must be at least 12 characters");
    }
    // First account becomes the administrator, matching the real backend.
    const user: User & { password: string } = {
      id: uuid(),
      email: normalised,
      role: state.users.length === 0 ? "admin" : "user",
      is_active: true,
      created_at: now(),
      last_login_at: now(),
      password,
    };
    state.users.push(user);
    state.session = user.id;
    save(state);
    audit("user_registered", "info", { role: user.role });
    return settle({ ...user, password: undefined } as unknown as User);
  },

  async login(email: string, password: string): Promise<User> {
    const user = state.users.find((u) => u.email === email.trim().toLowerCase());
    if (!user || user.password !== password) {
      throw new DemoError("invalid_credentials", "invalid email or password");
    }
    if (!user.is_active) throw new DemoError("account_inactive", "this account has been deactivated");
    user.last_login_at = now();
    state.session = user.id;
    save(state);
    audit("user_login");
    return settle({ ...user, password: undefined } as unknown as User);
  },

  async logout(): Promise<void> {
    audit("user_logout");
    state.session = null;
    save(state);
  },

  async me(): Promise<User> {
    return settle(currentUser(), 0);
  },

  restoreSession(): User | null {
    return state.session ? (state.users.find((u) => u.id === state.session) ?? null) : null;
  },

  async registerKey(bundle: {
    keyId: string;
    polyModulusDegree: number;
    totalCoeffModulusBits: number;
    hasRotationKeys: boolean;
    bundleBytes: number;
    slotCount: number;
    multiplicativeDepth: number;
    containsSecretKey: boolean;
  }): Promise<EncryptionKeyRecord> {
    // The check that matters. A real server does exactly this and refuses.
    if (bundle.containsSecretKey) {
      audit("key_rejected_secret_present", "critical", { key_id: bundle.keyId }, "encryption_key");
      throw new DemoError(
        "secret_key_rejected",
        "the uploaded bundle contains a secret key. Refusing to store it -- re-export without it and rotate this key.",
      );
    }
    const budget: Record<number, number> = { 4096: 109, 8192: 218, 16384: 438, 32768: 881 };
    const allowed = budget[bundle.polyModulusDegree] ?? 0;
    if (bundle.totalCoeffModulusBits > allowed) {
      throw new DemoError(
        "insecure_parameters",
        `${bundle.totalCoeffModulusBits} modulus bits exceeds the ${allowed}-bit budget for N=${bundle.polyModulusDegree} at 128-bit security`,
      );
    }

    state.keys.forEach((k) => {
      k.is_active = false;
    });
    const record: EncryptionKeyRecord = {
      id: uuid(),
      fingerprint: bundle.keyId,
      context_bytes: bundle.bundleBytes,
      poly_modulus_degree: bundle.polyModulusDegree,
      total_coeff_modulus_bits: bundle.totalCoeffModulusBits,
      security_level_bits: 128,
      has_galois_keys: bundle.hasRotationKeys,
      multiplicative_depth: bundle.multiplicativeDepth,
      slot_count: bundle.slotCount,
      is_active: true,
      label: "browser key",
      created_at: now(),
    };
    state.keys.unshift(record);
    save(state);
    audit(
      "key_registered",
      "info",
      {
        fingerprint: record.fingerprint,
        megabytes: +(record.context_bytes / 1e6).toFixed(2),
        rotation_keys: record.has_galois_keys,
      },
      "encryption_key",
    );
    return settle(record);
  },

  async activeKey(): Promise<EncryptionKeyRecord | null> {
    return settle(state.keys.find((k) => k.is_active) ?? null, 0);
  },

  async listKeys(): Promise<EncryptionKeyRecord[]> {
    return settle(state.keys, 0);
  },

  async uploadPortfolio(input: {
    name: string;
    tickers: string[];
    holdingsCiphertext: string;
    costBasisCiphertext: string | null;
  }): Promise<PortfolioRecord> {
    const key = state.keys.find((k) => k.is_active);
    if (!key) {
      throw new DemoError("encryption_key_not_found", "register an encryption key before uploading");
    }
    state.portfolios.forEach((p) => {
      p.is_active = false;
    });
    const bytes =
      Math.floor((input.holdingsCiphertext.length * 3) / 4) +
      (input.costBasisCiphertext ? Math.floor((input.costBasisCiphertext.length * 3) / 4) : 0);
    const record = {
      id: uuid(),
      name: input.name,
      tickers: input.tickers,
      n_assets: input.tickers.length,
      ciphertext_bytes: bytes,
      encryption_key_id: key.id,
      is_active: true,
      created_at: now(),
    };
    state.portfolios.unshift(record);
    ciphertexts.set(record.id, {
      holdings: input.holdingsCiphertext,
      costBasis: input.costBasisCiphertext,
    });
    save(state);
    audit(
      "portfolio_uploaded",
      "info",
      { n_assets: record.n_assets, ciphertext_megabytes: +(bytes / 1e6).toFixed(3) },
      "portfolio",
    );
    return settle({ ...record, holdings_ciphertext: input.holdingsCiphertext });
  },

  async currentPortfolio(): Promise<PortfolioRecord | null> {
    const record = state.portfolios.find((p) => p.is_active);
    if (!record) return null;
    const stored = ciphertexts.get(record.id);
    return settle(
      {
        ...record,
        holdings_ciphertext: stored?.holdings,
        cost_basis_ciphertext: stored?.costBasis ?? null,
      },
      0,
    );
  },

  async listPortfolios(): Promise<PortfolioRecord[]> {
    return settle(state.portfolios, 0);
  },

  async deletePortfolio(id: string): Promise<void> {
    state.portfolios = state.portfolios.filter((p) => p.id !== id);
    ciphertexts.delete(id);
    save(state);
    audit("portfolio_deleted", "info", {}, "portfolio");
  },

  createJob(portfolioId: string): AdvisoryJobRecord {
    const job: AdvisoryJobRecord = {
      id: uuid(),
      status: "running",
      stage: "planning",
      progress: 0,
      portfolio_id: portfolioId,
      created_at: now(),
      finished_at: null,
      duration_ms: null,
      error_message: null,
      recommendation_ciphertext: null,
      run_metadata: {},
    };
    state.jobs.unshift(job);
    save(state);
    audit("advisory_started", "info", {}, "advisory_job");
    return job;
  },

  updateJob(id: string, patch: Partial<AdvisoryJobRecord>): AdvisoryJobRecord | null {
    const job = state.jobs.find((j) => j.id === id);
    if (!job) return null;
    Object.assign(job, patch);
    if (patch.recommendation_ciphertext) {
      recommendations.set(id, patch.recommendation_ciphertext);
    }
    save(state);
    if (patch.status === "completed") audit("advisory_completed", "info", {}, "advisory_job");
    return job;
  },

  async listJobs(): Promise<AdvisoryJobRecord[]> {
    return settle(
      state.jobs.map((j) => ({ ...j, recommendation_ciphertext: recommendations.get(j.id) ?? null })),
      0,
    );
  },

  async listAudit(): Promise<AuditRecord[]> {
    return settle(state.audit, 0);
  },

  async listUsers(): Promise<User[]> {
    return settle(
      state.users.map(({ password: _password, ...user }) => user),
      0,
    );
  },

  async setUserActive(id: string, active: boolean): Promise<void> {
    const user = state.users.find((u) => u.id === id);
    if (!user) throw new DemoError("not_found", "no such user");
    if (user.id === state.session && !active) {
      throw new DemoError("validation_failed", "an administrator cannot deactivate their own account");
    }
    user.is_active = active;
    save(state);
    audit(active ? "user_reactivated" : "user_deactivated", "warning", { target: user.email });
  },

  async health(cryptoSelftestMs: number, cryptoOk: boolean): Promise<SystemHealth> {
    return settle(
      {
        status: cryptoOk ? "ok" : "degraded",
        environment: "demo (in-browser)",
        uptime_seconds: (Date.now() - BOOT_TIME) / 1000,
        database_ok: true,
        database_latency_ms: 0.2,
        crypto_ok: cryptoOk,
        crypto_selftest_ms: cryptoSelftestMs,
        active_sessions: state.session ? 1 : 0,
        n_users: state.users.length,
        n_portfolios: state.portfolios.length,
        jobs_running: state.jobs.filter((j) => j.status === "running").length,
        jobs_failed_24h: state.jobs.filter((j) => j.status === "failed").length,
      },
      0,
    );
  },

  async encryptionStats(): Promise<EncryptionStats> {
    const totalKeyBytes = state.keys.reduce((sum, k) => sum + k.context_bytes, 0);
    const totalCipherBytes = state.portfolios.reduce((sum, p) => sum + p.ciphertext_bytes, 0);
    return settle(
      {
        total_keys: state.keys.length,
        active_keys: state.keys.filter((k) => k.is_active).length,
        total_megabytes: +(totalKeyBytes / 1e6).toFixed(2),
        mean_key_megabytes: state.keys.length ? +(totalKeyBytes / state.keys.length / 1e6).toFixed(2) : 0,
        with_galois_keys: state.keys.filter((k) => k.has_galois_keys).length,
        total_portfolios: state.portfolios.length,
        total_ciphertext_megabytes: +(totalCipherBytes / 1e6).toFixed(3),
        mean_ciphertext_kilobytes: state.portfolios.length
          ? +(totalCipherBytes / state.portfolios.length / 1e3).toFixed(2)
          : 0,
      },
      0,
    );
  },
};
