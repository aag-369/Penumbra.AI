import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { BarList } from "../components/charts";
import { Alert, Badge, Button, CiphertextBlock, Dot, EmptyState, KeyValue, Panel, Progress, Stat } from "../components/ui";
import { demoBackend } from "../lib/demoBackend";
import { money, ms, num, percent } from "../lib/format";
import { covarianceFor, meanReturnsFor, pricesFor } from "../lib/market";
import { meanVariance, planTrades, portfolioStats, riskAversionFor, type Trade } from "../lib/optimizer";
import type { JobStage } from "../lib/types";
import { useApp } from "../store/AppContext";

const STAGES: { id: JobStage; label: string; detail: string }[] = [
  { id: "planning", label: "Planning agent", detail: "Turning stated goals into formal constraints" },
  { id: "risk", label: "Risk agent", detail: "Estimating returns and covariance from public market history" },
  { id: "qubo", label: "QUBO formulation", detail: "Binarising weights and encoding constraints as penalties" },
  { id: "optimization", label: "Optimisation", detail: "Solving for the allocation" },
  { id: "execution", label: "Execution simulation", detail: "Pricing the rebalancing trades" },
];

interface Result {
  weights: number[];
  stats: ReturnType<typeof portfolioStats>;
  current: ReturnType<typeof portfolioStats>;
  trades: Trade[];
  totalCost: number;
  runtimeMs: number;
  iterations: number;
  recommendationCiphertext: string;
  decrypted: number[];
}

export default function AdvisorPage() {
  const { portfolio, holdings, engine, serverEngine, keyState } = useApp();
  const navigate = useNavigate();

  const [riskTolerance, setRiskTolerance] = useState(6);
  const [horizon, setHorizon] = useState(10);
  const [maxPosition, setMaxPosition] = useState(35);
  const [stage, setStage] = useState<JobStage | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (keyState !== "ready" || !portfolio || !holdings) {
    return (
      <EmptyState
        title="Upload a portfolio to get advice"
        action={<Button onClick={() => navigate("/portfolio")}>Go to portfolio</Button>}
      >
        The advisory pipeline reasons over your encrypted holdings, so there needs to be one.
      </EmptyState>
    );
  }

  const tickers = portfolio.tickers;
  const prices = pricesFor(tickers);
  const values = holdings.map((q, i) => q * (prices[i] ?? 0));
  const totalValue = values.reduce((sum, v) => sum + v, 0);
  const currentWeights = values.map((v) => (totalValue > 0 ? v / totalValue : 0));

  async function run() {
    if (!engine || !serverEngine || !portfolio) return;
    setError(null);
    setResult(null);
    const job = demoBackend.createJob(portfolio.id);
    const started = performance.now();

    try {
      // Walk the stages with a visible pause each. A real run takes minutes
      // because of QAOA simulation; pretending it is instant would misrepresent
      // what the architecture costs.
      for (const step of STAGES) {
        setStage(step.id);
        demoBackend.updateJob(job.id, { stage: step.id, progress: STAGES.indexOf(step) / STAGES.length });
        await new Promise((resolve) => setTimeout(resolve, 420));
      }

      const meanReturns = meanReturnsFor(tickers);
      const covariance = covarianceFor(tickers);
      const allocation = meanVariance(meanReturns, covariance, {
        riskAversion: riskAversionFor(riskTolerance),
        maxPosition: maxPosition / 100,
      });

      // The recommendation is encrypted under the user's key before it is
      // stored. The server writes it and cannot read it back.
      const recommendationCiphertext = serverEngine.encrypt(allocation.weights);
      const decrypted = engine.decrypt(recommendationCiphertext, tickers.length);

      const { trades, totalCost } = planTrades(tickers, currentWeights, allocation.weights, totalValue);

      demoBackend.updateJob(job.id, {
        status: "completed",
        stage: "done",
        progress: 1,
        finished_at: new Date().toISOString(),
        duration_ms: Math.round(performance.now() - started),
        recommendation_ciphertext: recommendationCiphertext,
        run_metadata: { solver: "projected-gradient", iterations: allocation.iterations },
      });

      setResult({
        weights: allocation.weights,
        stats: portfolioStats(allocation.weights, meanReturns, covariance),
        current: portfolioStats(currentWeights, meanReturns, covariance),
        trades,
        totalCost,
        runtimeMs: allocation.runtimeMs,
        iterations: allocation.iterations,
        recommendationCiphertext,
        decrypted,
      });
      setStage("done");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "advisory run failed");
      demoBackend.updateJob(job.id, { status: "failed", error_message: String(cause) });
      setStage(null);
    }
  }

  const running = stage !== null && stage !== "done";
  const stageIndex = stage ? STAGES.findIndex((s) => s.id === stage) : -1;

  return (
    <div className="space-y-6 animate-riseIn">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Advisor</h1>
        <p className="mt-1 text-sm text-mist-dim">
          Goals are plaintext — you state them. Holdings stay encrypted throughout.
        </p>
      </header>

      <div className="grid items-start gap-6 lg:grid-cols-[340px_1fr]">
        <div className="space-y-6 lg:sticky lg:top-20 lg:self-start">
          <Panel title="Your goals">
            <div className="space-y-5">
              <div>
                <div className="flex items-baseline justify-between">
                  <span className="label">Risk tolerance</span>
                  <span className="font-mono text-sm text-mist">{riskTolerance} / 10</span>
                </div>
                <input
                  type="range"
                  min={1}
                  max={10}
                  value={riskTolerance}
                  onChange={(e) => setRiskTolerance(Number(e.target.value))}
                  className="mt-2 w-full accent-[#8b5cf6]"
                />
                <p className="mt-1.5 text-[11px] text-mist-faint">
                  λ = {num(riskAversionFor(riskTolerance), 2)} in the mean-variance objective
                </p>
              </div>

              <div>
                <div className="flex items-baseline justify-between">
                  <span className="label">Horizon</span>
                  <span className="font-mono text-sm text-mist">{horizon} years</span>
                </div>
                <input
                  type="range"
                  min={1}
                  max={40}
                  value={horizon}
                  onChange={(e) => setHorizon(Number(e.target.value))}
                  className="mt-2 w-full accent-[#8b5cf6]"
                />
              </div>

              <div>
                <div className="flex items-baseline justify-between">
                  <span className="label">Max single position</span>
                  <span className="font-mono text-sm text-mist">{maxPosition}%</span>
                </div>
                <input
                  type="range"
                  min={Math.ceil(100 / tickers.length)}
                  max={100}
                  value={maxPosition}
                  onChange={(e) => setMaxPosition(Number(e.target.value))}
                  className="mt-2 w-full accent-[#8b5cf6]"
                />
                <p className="mt-1.5 text-[11px] text-mist-faint">
                  Must be at least {Math.ceil(100 / tickers.length)}% or {tickers.length} assets cannot
                  reach 100%.
                </p>
              </div>

              <Button onClick={run} loading={running} className="w-full">
                {result ? "Run again" : "Generate recommendation"}
              </Button>
            </div>
          </Panel>

          <Panel title="Pipeline">
            <ol className="space-y-3">
              {STAGES.map((step, index) => {
                const done = stage === "done" || (stageIndex >= 0 && index < stageIndex);
                const active = stage === step.id;
                return (
                  <li key={step.id} className="flex gap-3">
                    <span className="mt-1.5">
                      <Dot tone={done ? "ok" : active ? "umbra" : "neutral"} pulse={active} />
                    </span>
                    <div className="min-w-0">
                      <div className={`text-xs font-medium ${done || active ? "text-mist" : "text-mist-faint"}`}>
                        {step.label}
                      </div>
                      <div className="text-[11px] leading-relaxed text-mist-faint">{step.detail}</div>
                    </div>
                  </li>
                );
              })}
            </ol>
            {running && (
              <div className="mt-4">
                <Progress value={(stageIndex + 1) / STAGES.length} />
              </div>
            )}
            <Alert tone="neutral" title="What is real here">
              The optimiser is a genuine projected-gradient mean-variance solver, and the recommendation
              really is encrypted under your key before it is stored. The agent layer and the QAOA
              solver are Phase 2 and 4 in the backend — the stages above name them honestly rather than
              implying they ran.
            </Alert>
          </Panel>
        </div>

        <div className="space-y-6">
          {error && <Alert tone="bad" title="The run failed">{error}</Alert>}

          {!result && !running && (
            <EmptyState title="No recommendation yet">
              Set your goals and run the pipeline. Nothing is precomputed — the allocation is solved when
              you press the button.
            </EmptyState>
          )}

          {result && (
            <>
              <div className="grid gap-4 sm:grid-cols-4">
                <Stat
                  label="Expected return"
                  value={percent(result.stats.expectedReturn)}
                  tone="ok"
                  sub={`from ${percent(result.current.expectedReturn)}`}
                />
                <Stat
                  label="Volatility"
                  value={percent(result.stats.volatility)}
                  sub={`from ${percent(result.current.volatility)}`}
                />
                <Stat
                  label="Sharpe"
                  value={num(result.stats.sharpe, 2)}
                  tone={result.stats.sharpe > result.current.sharpe ? "ok" : "warn"}
                  sub={`from ${num(result.current.sharpe, 2)}`}
                />
                <Stat label="Solver" value={`${result.iterations}`} sub={`iterations, ${ms(result.runtimeMs)}`} />
              </div>

              <Panel
                title="Recommended allocation"
                subtitle="Encrypted under your key, then decrypted here"
                actions={<Badge tone="cipher"><Dot tone="cipher" /> round-tripped</Badge>}
              >
                <BarList
                  rows={tickers
                    .map((ticker, index) => ({
                      label: ticker,
                      value: result.weights[index] ?? 0,
                      compare: currentWeights[index] ?? 0,
                    }))
                    .sort((a, b) => b.value - a.value)}
                  valueLabel="target"
                  compareLabel="current"
                />
                <div className="mt-5 space-y-3 border-t border-ink-700 pt-4">
                  <CiphertextBlock
                    ciphertext={result.recommendationCiphertext}
                    bytes={Math.floor((result.recommendationCiphertext.length * 3) / 4)}
                    label="recommendation ciphertext (as stored)"
                    chars={200}
                  />
                  <p className="text-xs leading-relaxed text-mist-faint">
                    Decrypted first three weights:{" "}
                    <span className="font-mono text-mist">
                      {result.decrypted.slice(0, 3).map((w) => percent(Math.max(w, 0), 2)).join(", ")}
                    </span>
                    . The store holds only the ciphertext above.
                  </p>
                </div>
              </Panel>

              <Panel title="Rebalancing plan" subtitle="Linear slippage model — see the note below">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-[11px] uppercase tracking-wider text-mist-faint">
                      <tr className="border-b border-ink-700">
                        <th className="py-2 pr-3 text-left font-medium">Ticker</th>
                        <th className="py-2 pr-3 text-left font-medium">Side</th>
                        <th className="py-2 pr-3 text-right font-medium">Current</th>
                        <th className="py-2 pr-3 text-right font-medium">Target</th>
                        <th className="py-2 pr-3 text-right font-medium">Notional</th>
                        <th className="py-2 text-right font-medium">Cost</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-ink-700/70">
                      {result.trades.map((trade) => (
                        <tr key={trade.ticker} className="transition-colors hover:bg-ink-800/60">
                          <td className="py-2 pr-3 font-mono text-[13px] text-mist">{trade.ticker}</td>
                          <td className="py-2 pr-3">
                            <span
                              className={`font-mono text-[11px] ${
                                trade.side === "BUY" ? "text-ok" : trade.side === "SELL" ? "text-bad" : "text-mist-faint"
                              }`}
                            >
                              {trade.side}
                            </span>
                          </td>
                          <td className="py-2 pr-3 text-right font-mono text-[13px] text-mist-dim">
                            {percent(trade.currentWeight)}
                          </td>
                          <td className="py-2 pr-3 text-right font-mono text-[13px] text-mist">
                            {percent(trade.targetWeight)}
                          </td>
                          <td className="py-2 pr-3 text-right font-mono text-[13px] text-mist-dim">
                            {money(trade.notional)}
                          </td>
                          <td className="py-2 text-right font-mono text-[13px] text-mist-dim">
                            {trade.cost > 0 ? money(trade.cost) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="mt-4">
                  <KeyValue
                    rows={[
                      ["Total execution cost", money(result.totalCost)],
                      ["As a share of portfolio", percent(result.totalCost / totalValue, 3)],
                      ["Trades to place", result.trades.filter((t) => t.side !== "HOLD").length],
                    ]}
                  />
                </div>
                <Alert tone="neutral" title="Why slippage is linear here">
                  A square-root market-impact model fits the data better, but it cannot be evaluated
                  under CKKS without a polynomial approximation. Using the linear model keeps this
                  consistent with what the encrypted pipeline could actually compute, rather than
                  quoting a cost the real system could not produce.
                </Alert>
              </Panel>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
