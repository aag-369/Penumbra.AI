/**
 * Portfolio optimisation, in TypeScript.
 *
 * This is the browser-side twin of `backend/app/optimization/classical_baseline.py`.
 * It exists so the advisory pipeline produces a real, defensible allocation when
 * the app runs without a backend -- rather than a hard-coded "recommendation"
 * that would be embarrassing under questioning.
 *
 * Projected gradient ascent rather than SLSQP: no solver dependency, and the
 * problem is convex when the covariance is positive semi-definite, so a
 * projection onto the simplex at every step converges to the same optimum.
 */

export interface Allocation {
  weights: number[];
  objective: number;
  iterations: number;
  runtimeMs: number;
  converged: boolean;
}

export interface PortfolioStats {
  expectedReturn: number;
  volatility: number;
  sharpe: number;
  herfindahl: number;
  effectiveHoldings: number;
}

const RISK_FREE = 0.02;

function matVec(matrix: number[][], vector: number[]): number[] {
  return matrix.map((row) => row.reduce((sum, value, j) => sum + value * vector[j]!, 0));
}

function dot(a: number[], b: number[]): number {
  return a.reduce((sum, value, i) => sum + value * b[i]!, 0);
}

/**
 * Euclidean projection onto `{w : sum(w) = 1, lo <= w_i <= hi}`.
 *
 * Bisection on the dual variable. Simple, and the clamped simplex has no
 * closed form once box bounds are involved.
 */
function projectToSimplex(vector: number[], lo: number, hi: number): number[] {
  const n = vector.length;
  if (hi * n < 1) throw new Error(`max position ${hi} across ${n} assets cannot total 1.0`);

  let low = Math.min(...vector) - hi - 1;
  let high = Math.max(...vector) - lo + 1;
  for (let step = 0; step < 100; step += 1) {
    const mid = (low + high) / 2;
    const total = vector.reduce((sum, v) => sum + Math.min(hi, Math.max(lo, v - mid)), 0);
    if (total > 1) low = mid;
    else high = mid;
  }
  const theta = (low + high) / 2;
  return vector.map((v) => Math.min(hi, Math.max(lo, v - theta)));
}

/**
 * Maximise `mu'w - lambda * w'Sigma w` subject to a budget and box bounds.
 */
export function meanVariance(
  meanReturns: number[],
  covariance: number[][],
  {
    riskAversion = 2,
    minPosition = 0,
    maxPosition = 1,
    maxIterations = 4000,
  }: { riskAversion?: number; minPosition?: number; maxPosition?: number; maxIterations?: number } = {},
): Allocation {
  const started = performance.now();
  const n = meanReturns.length;
  let weights = projectToSimplex(new Array(n).fill(1 / n), minPosition, maxPosition);

  const scale = Math.max(...covariance.map((row) => Math.max(...row.map(Math.abs))), 1e-9);
  const stepSize = 1 / (2 * riskAversion * scale * n + 1);

  let iterations = 0;
  let converged = false;
  for (; iterations < maxIterations; iterations += 1) {
    // d/dw [mu'w - lambda w'Sigma w] = mu - 2*lambda*Sigma*w
    const sigmaW = matVec(covariance, weights);
    const gradient = meanReturns.map((mu, i) => mu - 2 * riskAversion * sigmaW[i]!);
    const next = projectToSimplex(
      weights.map((w, i) => w + stepSize * gradient[i]!),
      minPosition,
      maxPosition,
    );
    const shift = Math.max(...next.map((w, i) => Math.abs(w - weights[i]!)));
    weights = next;
    if (shift < 1e-10) {
      converged = true;
      break;
    }
  }

  const objective = dot(weights, meanReturns) - riskAversion * dot(weights, matVec(covariance, weights));
  return { weights, objective, iterations, runtimeMs: performance.now() - started, converged };
}

export function portfolioStats(
  weights: number[],
  meanReturns: number[],
  covariance: number[][],
): PortfolioStats {
  const expectedReturn = dot(weights, meanReturns);
  const variance = Math.max(dot(weights, matVec(covariance, weights)), 0);
  const volatility = Math.sqrt(variance);
  const herfindahl = weights.reduce((sum, w) => sum + w * w, 0);
  return {
    expectedReturn,
    volatility,
    sharpe: volatility > 1e-9 ? (expectedReturn - RISK_FREE) / volatility : 0,
    herfindahl,
    effectiveHoldings: herfindahl > 0 ? 1 / herfindahl : 0,
  };
}

/**
 * Map a 1-10 risk tolerance onto a risk-aversion coefficient.
 *
 * Geometric rather than linear: the difference between "very conservative" and
 * "conservative" should be a larger change in lambda than the difference between
 * "aggressive" and "very aggressive", because the efficient frontier flattens.
 */
export function riskAversionFor(tolerance: number): number {
  const clamped = Math.min(10, Math.max(1, tolerance));
  return 12 * Math.pow(0.72, clamped - 1);
}

export interface Trade {
  ticker: string;
  currentWeight: number;
  targetWeight: number;
  deltaWeight: number;
  side: "BUY" | "SELL" | "HOLD";
  notional: number;
  slippageBps: number;
  commission: number;
  cost: number;
}

/**
 * Rebalancing trades with an execution-cost model.
 *
 * Slippage is linear in trade size rather than square-root. A square-root market
 * impact model is the better fit empirically, but it cannot be evaluated under
 * CKKS without a polynomial approximation -- so the linear model is what the
 * encrypted pipeline can actually honour, and using it here keeps the demo
 * consistent with what the real system could compute. Noted rather than hidden.
 */
export function planTrades(
  tickers: string[],
  currentWeights: number[],
  targetWeights: number[],
  totalValue: number,
): { trades: Trade[]; totalCost: number } {
  const trades: Trade[] = tickers.map((ticker, i) => {
    const currentWeight = currentWeights[i] ?? 0;
    const targetWeight = targetWeights[i] ?? 0;
    const deltaWeight = targetWeight - currentWeight;
    const notional = Math.abs(deltaWeight) * totalValue;
    const slippageBps = notional === 0 ? 0 : 2 + (notional / totalValue) * 18;
    const commission = notional === 0 ? 0 : Math.max(1, notional * 0.0002);
    return {
      ticker,
      currentWeight,
      targetWeight,
      deltaWeight,
      side: Math.abs(deltaWeight) < 0.001 ? "HOLD" : deltaWeight > 0 ? "BUY" : "SELL",
      notional,
      slippageBps,
      commission,
      cost: (notional * slippageBps) / 10000 + commission,
    };
  });
  return { trades, totalCost: trades.reduce((sum, t) => sum + t.cost, 0) };
}
