import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { allocationColors, BarList, DonutChart } from "../components/charts";
import { Alert, Badge, Button, Dot, EmptyState, Panel, Stat } from "../components/ui";
import { money, ms, num, percent, sci } from "../lib/format";
import { covarianceFor, lookup, meanReturnsFor, pricesFor, sectorOf } from "../lib/market";
import { portfolioStats } from "../lib/optimizer";
import { useApp } from "../store/AppContext";

export default function DashboardPage() {
  const { portfolio, holdings, engine, serverEngine, keyState } = useApp();
  const navigate = useNavigate();

  const [encryptedValue, setEncryptedValue] = useState<number | null>(null);
  const [computeMs, setComputeMs] = useState(0);
  const [computeError, setComputeError] = useState<string | null>(null);

  const tickers = portfolio?.tickers ?? [];
  const prices = pricesFor(tickers);

  /**
   * Compute the portfolio's value the way the real system would: the *server*
   * engine does the arithmetic over the ciphertext, and only the client
   * decrypts. Both run in this tab, but they are separate objects and the
   * server one has no decryptor at all.
   */
  useEffect(() => {
    if (!portfolio?.holdings_ciphertext || !serverEngine || !engine) return;
    setComputeError(null);
    try {
      const started = performance.now();
      const encrypted = serverEngine.dotPlain(portfolio.holdings_ciphertext, prices);
      const elapsed = performance.now() - started;
      setEncryptedValue(engine.decrypt(encrypted, 1)[0] ?? null);
      setComputeMs(elapsed);
    } catch (cause) {
      setComputeError(cause instanceof Error ? cause.message : "computation failed");
      setEncryptedValue(null);
    }
    // `prices` is derived from tickers; depending on the joined string keeps the
    // effect from re-running on every render for an unchanged portfolio.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [portfolio?.id, portfolio?.holdings_ciphertext, serverEngine, engine, tickers.join(",")]);

  if (keyState !== "ready") {
    return (
      <EmptyState title="Unlock your key to see your portfolio" action={<Button onClick={() => navigate("/keys")}>Go to keys</Button>}>
        Everything on this page is decrypted locally, so it needs the key that is currently locked.
      </EmptyState>
    );
  }

  if (!portfolio || !holdings) {
    return (
      <EmptyState title="No portfolio yet" action={<Button onClick={() => navigate("/portfolio")}>Upload a portfolio</Button>}>
        Upload a CSV of holdings. It is encrypted in this browser before it is stored.
      </EmptyState>
    );
  }

  const values = holdings.map((quantity, index) => quantity * (prices[index] ?? 0));
  const totalValue = values.reduce((sum, v) => sum + v, 0);
  const weights = values.map((v) => (totalValue > 0 ? v / totalValue : 0));

  const meanReturns = meanReturnsFor(tickers);
  const covariance = covarianceFor(tickers);
  const stats = portfolioStats(weights, meanReturns, covariance);

  const sectorTotals = new Map<string, number>();
  tickers.forEach((ticker, index) => {
    const sector = sectorOf(ticker);
    sectorTotals.set(sector, (sectorTotals.get(sector) ?? 0) + (weights[index] ?? 0));
  });

  // Sorted once, so the donut and the bars agree on both order and colour.
  const sortedWeights = tickers
    .map((ticker, index) => ({ label: ticker, value: weights[index] ?? 0 }))
    .sort((a, b) => b.value - a.value);
  const palette = allocationColors(sortedWeights.map((row) => row.label));
  const weightRows = sortedWeights.map((row) => ({ ...row, color: palette.get(row.label) }));

  const relativeError =
    encryptedValue !== null && totalValue > 0 ? Math.abs(encryptedValue - totalValue) / totalValue : null;

  return (
    <div className="space-y-6 animate-riseIn">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{portfolio.name}</h1>
          <p className="mt-1 text-sm text-mist-dim">
            {portfolio.n_assets} holdings · decrypted locally · valued at reference prices
          </p>
        </div>
        <Badge tone="cipher">
          <Dot tone="cipher" /> stored encrypted
        </Badge>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Portfolio value" value={money(totalValue)} tone="umbra" sub="decrypted in this browser" />
        <Stat label="Expected return" value={percent(stats.expectedReturn)} sub="annualised, reference data" />
        <Stat label="Volatility" value={percent(stats.volatility)} sub="annualised" />
        <Stat
          label="Sharpe ratio"
          value={num(stats.sharpe, 2)}
          tone={stats.sharpe > 1 ? "ok" : stats.sharpe > 0.5 ? "warn" : "bad"}
          sub="excess return per unit risk"
        />
      </div>

      <Panel
        title="The same number, computed without decryption"
        subtitle="The server-side engine evaluates over the ciphertext; only this browser can open the result"
      >
        {computeError ? (
          <Alert tone="warn" title="Server-side computation unavailable">
            {computeError}
          </Alert>
        ) : encryptedValue === null ? (
          <p className="text-sm text-mist-faint">Computing…</p>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-3">
              <Stat label="Homomorphic result" value={money(encryptedValue)} tone="cipher" sub={`${ms(computeMs)} on this machine`} />
              <Stat label="Plaintext result" value={money(totalValue)} sub="computed locally for comparison" />
              <Stat
                label="Relative error"
                value={relativeError === null ? "—" : sci(relativeError)}
                tone="ok"
                sub="CKKS is approximate arithmetic"
              />
            </div>
            <Alert tone="cipher" title="What just happened">
              The evaluator multiplied your encrypted holdings by public prices and summed the slots —
              one multiplication and a rotate-and-add reduction — without holding a secret key. The
              result came back encrypted and was opened here. The error of {relativeError === null ? "—" : sci(relativeError)}{" "}
              is CKKS rounding, not a bug: the scheme trades exactness for the ability to compute at all.
            </Alert>
          </>
        )}
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Allocation" subtitle="Share of total value">
          <DonutChart
            slices={tickers.map((ticker, index) => ({ label: ticker, value: values[index] ?? 0 }))}
            centerLabel="Total"
            centerValue={money(totalValue)}
          />
        </Panel>

        <Panel title="Weights" subtitle="Precise values — a donut cannot be read for close comparisons">
          <BarList rows={weightRows} />
        </Panel>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <Panel title="Holdings" subtitle="Decrypted in this browser; the server sees only tickers">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[11px] uppercase tracking-wider text-mist-faint">
                <tr className="border-b border-ink-700">
                  <th className="py-2 pr-3 text-left font-medium">Ticker</th>
                  <th className="py-2 pr-3 text-left font-medium">Sector</th>
                  <th className="py-2 pr-3 text-right font-medium">Quantity</th>
                  <th className="py-2 pr-3 text-right font-medium">Price</th>
                  <th className="py-2 pr-3 text-right font-medium">Value</th>
                  <th className="py-2 text-right font-medium">Weight</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-700/70">
                {tickers.map((ticker, index) => (
                  <tr key={ticker} className="transition-colors hover:bg-ink-800/60">
                    <td className="py-2 pr-3">
                      <div className="font-mono text-[13px] text-mist">{ticker}</div>
                      <div className="text-[11px] text-mist-faint">{lookup(ticker)?.name ?? "—"}</div>
                    </td>
                    <td className="py-2 pr-3 text-xs text-mist-faint">{sectorOf(ticker)}</td>
                    <td className="py-2 pr-3 text-right font-mono text-[13px] text-mist">
                      {num(holdings[index] ?? 0, 0)}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono text-[13px] text-mist-dim">
                      {money(prices[index] ?? 0)}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono text-[13px] text-mist">
                      {money(values[index] ?? 0)}
                    </td>
                    <td className="py-2 text-right font-mono text-[13px] text-mist">
                      {percent(weights[index] ?? 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <div className="space-y-6">
          <Panel title="Sector exposure">
            <BarList
              rows={[...sectorTotals.entries()]
                .map(([sector, weight]) => ({ label: sector, value: weight }))
                .sort((a, b) => b.value - a.value)}
              color="#199e70"
            />
          </Panel>

          <Panel title="Concentration">
            <div className="grid grid-cols-2 gap-3">
              <Stat label="Herfindahl index" value={num(stats.herfindahl, 3)} sub="1.0 = a single holding" />
              <Stat
                label="Effective holdings"
                value={num(stats.effectiveHoldings, 1)}
                sub={`of ${tickers.length} actual`}
              />
            </div>
            <p className="mt-4 text-xs leading-relaxed text-mist-faint">
              Effective holdings is the reciprocal of the Herfindahl index — the number of equally
              weighted positions that would give the same concentration. A gap between this and the
              actual count means the portfolio is more concentrated than it looks.
            </p>
          </Panel>
        </div>
      </div>
    </div>
  );
}
