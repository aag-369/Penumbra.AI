export interface User {
  id: string;
  email: string;
  role: "user" | "admin";
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface EncryptionKeyRecord {
  id: string;
  fingerprint: string;
  context_bytes: number;
  poly_modulus_degree: number;
  total_coeff_modulus_bits: number;
  security_level_bits: number;
  has_galois_keys: boolean;
  multiplicative_depth: number;
  slot_count: number;
  is_active: boolean;
  label: string | null;
  created_at: string;
}

export interface PortfolioRecord {
  id: string;
  name: string;
  tickers: string[];
  n_assets: number;
  ciphertext_bytes: number;
  encryption_key_id: string;
  is_active: boolean;
  created_at: string;
  holdings_ciphertext?: string;
  cost_basis_ciphertext?: string | null;
}

export interface InvestmentGoals {
  risk_tolerance: number;
  horizon_years: number;
  max_holdings?: number;
  max_position_pct?: number;
  excluded_sectors?: string[];
}

export type JobStage = "queued" | "planning" | "risk" | "qubo" | "optimization" | "execution" | "done";

export interface AdvisoryJobRecord {
  id: string;
  status: "pending" | "running" | "completed" | "failed";
  stage: JobStage;
  progress: number;
  portfolio_id: string;
  created_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  /** Encrypted under the user's key. The backend that wrote it cannot read it. */
  recommendation_ciphertext: string | null;
  run_metadata: Record<string, unknown>;
}

export interface AuditRecord {
  id: string;
  action: string;
  severity: "info" | "warning" | "critical";
  actor_user_id: string | null;
  resource_type: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface SystemHealth {
  status: string;
  environment: string;
  uptime_seconds: number;
  database_ok: boolean;
  database_latency_ms: number;
  crypto_ok: boolean;
  crypto_selftest_ms: number;
  active_sessions: number;
  n_users: number;
  n_portfolios: number;
  jobs_running: number;
  jobs_failed_24h: number;
}

export interface EncryptionStats {
  total_keys: number;
  active_keys: number;
  total_megabytes: number;
  mean_key_megabytes: number;
  with_galois_keys: number;
  total_portfolios: number;
  total_ciphertext_megabytes: number;
  mean_ciphertext_kilobytes: number;
}
