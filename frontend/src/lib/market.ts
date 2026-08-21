/**
 * Public market reference data.
 *
 * Fixed rather than fetched, on purpose. Prices, mean returns and the covariance
 * matrix are *public* information -- this is exactly the data that stays in
 * plaintext in the real architecture, because encrypting a public input protects
 * nothing while costing three orders of magnitude (see
 * `docs/SPEC_DEVIATIONS.md` #3). Freezing it also means a demo behaves the same
 * on a conference wifi as it does offline.
 *
 * Figures are plausible long-run annualised estimates, not live quotes, and the
 * UI says so wherever they appear.
 */

export interface Instrument {
  ticker: string;
  name: string;
  sector: string;
  price: number;
  /** Annualised expected return. */
  meanReturn: number;
  /** Annualised volatility. */
  volatility: number;
}

export const UNIVERSE: Instrument[] = [
  { ticker: "AAPL", name: "Apple", sector: "Technology", price: 227.5, meanReturn: 0.092, volatility: 0.26 },
  { ticker: "MSFT", name: "Microsoft", sector: "Technology", price: 415.2, meanReturn: 0.085, volatility: 0.24 },
  { ticker: "NVDA", name: "NVIDIA", sector: "Technology", price: 128.4, meanReturn: 0.145, volatility: 0.48 },
  { ticker: "JNJ", name: "Johnson & Johnson", sector: "Healthcare", price: 158.3, meanReturn: 0.052, volatility: 0.15 },
  { ticker: "UNH", name: "UnitedHealth", sector: "Healthcare", price: 512.7, meanReturn: 0.068, volatility: 0.22 },
  { ticker: "XOM", name: "Exxon Mobil", sector: "Energy", price: 118.9, meanReturn: 0.061, volatility: 0.28 },
  { ticker: "CVX", name: "Chevron", sector: "Energy", price: 152.4, meanReturn: 0.058, volatility: 0.26 },
  { ticker: "JPM", name: "JPMorgan Chase", sector: "Financials", price: 214.8, meanReturn: 0.074, volatility: 0.23 },
  { ticker: "BRK.B", name: "Berkshire Hathaway", sector: "Financials", price: 452.8, meanReturn: 0.066, volatility: 0.17 },
  { ticker: "PG", name: "Procter & Gamble", sector: "Consumer Staples", price: 168.2, meanReturn: 0.048, volatility: 0.14 },
  { ticker: "KO", name: "Coca-Cola", sector: "Consumer Staples", price: 71.3, meanReturn: 0.045, volatility: 0.15 },
  { ticker: "TSLA", name: "Tesla", sector: "Consumer Discretionary", price: 248.6, meanReturn: 0.118, volatility: 0.55 },
];

const BY_TICKER = new Map(UNIVERSE.map((i) => [i.ticker, i]));

export function lookup(ticker: string): Instrument | undefined {
  return BY_TICKER.get(ticker.toUpperCase());
}

/**
 * Prices for a ticker list. Unknown symbols get a neutral placeholder so an
 * uploaded portfolio containing something outside the sample universe still
 * works rather than erroring out mid-demo.
 */
export function pricesFor(tickers: string[]): number[] {
  return tickers.map((t) => lookup(t)?.price ?? 100);
}

export function meanReturnsFor(tickers: string[]): number[] {
  return tickers.map((t) => lookup(t)?.meanReturn ?? 0.06);
}

/** Correlation between two sectors: high within, moderate across. */
function sectorCorrelation(a: string, b: string): number {
  if (a === b) return 0.72;
  const defensive = new Set(["Healthcare", "Consumer Staples"]);
  const cyclical = new Set(["Technology", "Consumer Discretionary", "Financials"]);
  if (defensive.has(a) && defensive.has(b)) return 0.55;
  if (cyclical.has(a) && cyclical.has(b)) return 0.48;
  if ((defensive.has(a) && cyclical.has(b)) || (cyclical.has(a) && defensive.has(b))) return 0.22;
  return 0.3;
}

/**
 * Covariance matrix built from volatilities and a sector correlation model.
 *
 * Positive semi-definite by construction: every entry is
 * `rho_ij * sigma_i * sigma_j` with `rho` symmetric and unit diagonal.
 */
export function covarianceFor(tickers: string[]): number[][] {
  const vols = tickers.map((t) => lookup(t)?.volatility ?? 0.25);
  const sectors = tickers.map((t) => lookup(t)?.sector ?? "Other");
  return tickers.map((_, i) =>
    tickers.map((__, j) => {
      const rho = i === j ? 1 : sectorCorrelation(sectors[i]!, sectors[j]!);
      return rho * vols[i]! * vols[j]!;
    }),
  );
}

export function sectorOf(ticker: string): string {
  return lookup(ticker)?.sector ?? "Other";
}
