/**
 * The live demo's pipeline, as plain functions over the real engine.
 *
 * Two engines take part. The *client* is created here with a secret key. The
 * *server* is rebuilt from the client's public bundle -- exactly the object the
 * API constructs -- so it has evaluation keys and no decryptor. Every size and
 * timing returned is measured, on the visitor's machine, at the moment they
 * press the button.
 */

import { covarianceFor, meanReturnsFor, pricesFor } from "../lib/market";
import { meanVariance, planTrades, portfolioStats, riskAversionFor } from "../lib/optimizer";
import { CkksEngine, DEFAULT_PARAMS, loadSeal, sealIsLoaded, type KeyMetrics } from "../lib/seal";

/** The app's own sample portfolio (`SAMPLE_CSV`), so the demo and the app agree. */
export const DEMO_TICKERS = ["AAPL", "MSFT", "NVDA", "JNJ", "XOM", "JPM", "BRK.B", "UNH"];
export const DEMO_SHARES = [120, 85, 40, 210, 160, 95, 14, 30];
export const DEMO_PRICES = pricesFor(DEMO_TICKERS);

/** Let React paint before a long synchronous WebAssembly call blocks the thread. */
export function nextPaint(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, 16)));
}

// -- step 1: keys and encryption -------------------------------------------------

export interface KeySession {
  client: CkksEngine;
  metrics: KeyMetrics;
  sealLoadMs: number;
  sealWasCached: boolean;
  server: CkksEngine | null;
  serverBuildMs: number;
}

export async function loadSealTimed(): Promise<{ ms: number; cached: boolean }> {
  const cached = sealIsLoaded();
  const started = performance.now();
  await loadSeal();
  return { ms: performance.now() - started, cached };
}

export async function createKeySession(seal: { ms: number; cached: boolean }): Promise<KeySession> {
  const client = await CkksEngine.createClient(DEFAULT_PARAMS, { rotationKeys: true });
  return {
    client,
    metrics: client.metrics(),
    sealLoadMs: seal.ms,
    sealWasCached: seal.cached,
    server: null,
    serverBuildMs: 0,
  };
}

export interface Holdings {
  shares: number[];
  prices: number[];
  values: number[];
  total: number;
  weights: number[];
}

export function holdingsFor(shares: number[]): Holdings {
  const values = shares.map((q, i) => q * DEMO_PRICES[i]!);
  const total = values.reduce((a, b) => a + b, 0);
  return {
    shares,
    prices: DEMO_PRICES,
    values,
    total,
    weights: values.map((v) => (total > 0 ? v / total : 0)),
  };
}

export interface Encrypted {
  holdings: Holdings;
  sharesCt: string;
  weightsCt: string;
  sharesBytes: number;
  weightsBytes: number;
  encryptMs: number;
  levels: number;
}

/**
 * Weights are encoded in percentage points. CKKS noise is roughly constant in
 * absolute terms, so a return of 7.5 carries a hundred times less relative
 * error than a return of 0.075 -- a fixed-point choice, undone after decrypting.
 */
export const WEIGHT_SCALE = 100;

export function encryptHoldings(session: KeySession, holdings: Holdings): Encrypted {
  const { client } = session;
  const started = performance.now();
  const sharesCt = client.encryptReplicated(holdings.shares);
  const weightsCt = client.encryptReplicated(holdings.weights.map((w) => w * WEIGHT_SCALE));
  const encryptMs = performance.now() - started;
  return {
    holdings,
    sharesCt,
    weightsCt,
    sharesBytes: client.ciphertextBytes(sharesCt),
    weightsBytes: client.ciphertextBytes(weightsCt),
    encryptMs,
    levels: client.levelsRemaining(sharesCt),
  };
}

// -- step 2: the server ------------------------------------------------------------

export interface ServerOp {
  id: "value" | "return" | "risk";
  label: string;
  formula: string;
  detail: string;
  ms: number;
  levelsLeft: number;
}

export interface ServerRun {
  serverBuildMs: number;
  reusedServer: boolean;
  bundleBytes: number;
  refusal: string;
  ops: ServerOp[];
  results: { value: string; ret: string; risk: string };
  computeMs: number;
  resultBytes: number;
}

export async function runServer(session: KeySession, encrypted: Encrypted): Promise<ServerRun> {
  let reusedServer = true;
  if (!session.server) {
    reusedServer = false;
    const started = performance.now();
    session.server = await CkksEngine.fromPublicBundle(session.client.exportPublicBundle());
    session.serverBuildMs = performance.now() - started;
  }
  const server = session.server;

  let refusal = "";
  try {
    server.decrypt(encrypted.sharesCt);
    refusal = "the server decrypted it -- this should be impossible";
  } catch (cause) {
    refusal = cause instanceof Error ? cause.message : String(cause);
  }

  const tickers = DEMO_TICKERS;
  const mu = meanReturnsFor(tickers);
  const sigma = covarianceFor(tickers);

  const timed = <T>(fn: () => T): [T, number] => {
    const started = performance.now();
    const out = fn();
    return [out, performance.now() - started];
  };

  const [value, valueMs] = timed(() =>
    server.dotPlainPeriodic(encrypted.sharesCt, encrypted.holdings.prices),
  );
  const [ret, retMs] = timed(() => server.dotPlainPeriodic(encrypted.weightsCt, mu));
  const [risk, riskMs] = timed(() => server.quadraticFormPeriodic(encrypted.weightsCt, sigma));

  const ops: ServerOp[] = [
    {
      id: "value",
      label: "Portfolio value",
      formula: "Σ qᵢ·pᵢ",
      detail: "multiply_plain · rescale · 3 rotate-and-add",
      ms: valueMs,
      levelsLeft: server.levelsRemaining(value),
    },
    {
      id: "return",
      label: "Expected return",
      formula: "μ⊤w",
      detail: "multiply_plain · rescale · 3 rotate-and-add",
      ms: retMs,
      levelsLeft: server.levelsRemaining(ret),
    },
    {
      id: "risk",
      label: "Markowitz risk term",
      formula: "w⊤Σw",
      detail: "7 rotations × multiply_plain · multiply · relinearize · rescale · 3 rotate-and-add",
      ms: riskMs,
      levelsLeft: server.levelsRemaining(risk),
    },
  ];

  return {
    serverBuildMs: session.serverBuildMs,
    reusedServer,
    bundleBytes: session.metrics.publicBundleBytes,
    refusal,
    ops,
    results: { value, ret, risk },
    computeMs: valueMs + retMs + riskMs,
    resultBytes: [value, ret, risk].reduce((sum, c) => sum + server.ciphertextBytes(c), 0),
  };
}

// -- step 3: decrypt ---------------------------------------------------------------

export interface Decrypted {
  value: number;
  ret: number;
  variance: number;
  volatility: number;
  truth: { value: number; ret: number; variance: number };
  errors: { value: number; ret: number; variance: number };
  worstError: number;
  decryptMs: number;
}

export function decryptResults(session: KeySession, encrypted: Encrypted, run: ServerRun): Decrypted {
  const { client } = session;
  const started = performance.now();
  const value = client.decrypt(run.results.value, 1)[0] ?? 0;
  const ret = (client.decrypt(run.results.ret, 1)[0] ?? 0) / WEIGHT_SCALE;
  const variance = (client.decrypt(run.results.risk, 1)[0] ?? 0) / (WEIGHT_SCALE * WEIGHT_SCALE);
  const decryptMs = performance.now() - started;

  const { weights, total } = encrypted.holdings;
  const mu = meanReturnsFor(DEMO_TICKERS);
  const sigma = covarianceFor(DEMO_TICKERS);
  const truth = {
    value: total,
    ret: weights.reduce((s, w, i) => s + w * mu[i]!, 0),
    variance: weights.reduce(
      (s, wi, i) => s + wi * sigma[i]!.reduce((t, sij, j) => t + sij * weights[j]!, 0),
      0,
    ),
  };
  const rel = (a: number, b: number) => (b === 0 ? Math.abs(a) : Math.abs(a - b) / Math.abs(b));
  const errors = {
    value: rel(value, truth.value),
    ret: rel(ret, truth.ret),
    variance: rel(variance, truth.variance),
  };
  return {
    value,
    ret,
    variance,
    volatility: Math.sqrt(Math.max(variance, 0)),
    truth,
    errors,
    worstError: Math.max(errors.value, errors.ret, errors.variance),
    decryptMs,
  };
}

// -- step 4: recommendation --------------------------------------------------------

export interface Move {
  ticker: string;
  side: "BUY" | "SELL";
  deltaWeight: number;
}

export interface Recommendation {
  trades: number;
  turnover: number;
  currentSharpe: number;
  targetSharpe: number;
  targetReturn: number;
  targetVolatility: number;
  moves: Move[];
  riskAversion: number;
}

/**
 * The same mean-variance optimiser the app's Advisor page uses, at its default
 * settings (risk tolerance 6/10, 35% position cap). It runs on this device --
 * the server-side QAOA path is Phase 4.
 */
export function recommend(encrypted: Encrypted, decrypted: Decrypted): Recommendation {
  const mu = meanReturnsFor(DEMO_TICKERS);
  const sigma = covarianceFor(DEMO_TICKERS);
  const riskAversion = riskAversionFor(6);
  const target = meanVariance(mu, sigma, { riskAversion, maxPosition: 0.35 }).weights;
  const current = encrypted.holdings.weights;
  const { trades } = planTrades(DEMO_TICKERS, current, target, decrypted.value);
  const stats = portfolioStats(target, mu, sigma);
  const acting = trades.filter((t) => t.side !== "HOLD");
  return {
    trades: acting.length,
    turnover: acting.reduce((s, t) => s + Math.abs(t.deltaWeight), 0) / 2,
    currentSharpe: decrypted.volatility > 0 ? (decrypted.ret - 0.02) / decrypted.volatility : 0,
    targetSharpe: stats.sharpe,
    targetReturn: stats.expectedReturn,
    targetVolatility: stats.volatility,
    moves: acting
      .slice()
      .sort((a, b) => Math.abs(b.deltaWeight) - Math.abs(a.deltaWeight))
      .slice(0, 4)
      .map((t) => ({ ticker: t.ticker, side: t.side as "BUY" | "SELL", deltaWeight: t.deltaWeight })),
    riskAversion,
  };
}
