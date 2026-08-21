/**
 * Portfolio CSV parsing, mirroring `PortfolioService.parse_csv` on the server.
 *
 * Deliberately duplicated rather than round-tripped through the API: parsing
 * here means the quantities never leave the browser unencrypted, which is the
 * point. The server's copy exists only for a dry-run shape check.
 */

export interface ParsedPortfolio {
  tickers: string[];
  quantities: number[];
  costBasis: number[] | null;
}

export class CsvError extends Error {
  constructor(readonly problems: string[]) {
    super(problems.join("; "));
  }
}

const TICKER = /^[A-Z][A-Z0-9]{0,9}([.\-][A-Z]{1,4})?$/;

/** Split one CSV line, honouring double quotes so "1,250" survives as a field. */
function splitLine(line: string): string[] {
  const fields: string[] = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === "," && !inQuotes) {
      fields.push(current);
      current = "";
    } else {
      current += ch;
    }
  }
  fields.push(current);
  return fields;
}

export function parsePortfolioCsv(text: string): ParsedPortfolio {
  const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter((l) => l.trim() !== "");
  if (lines.length === 0) throw new CsvError(["file is empty"]);

  const header = splitLine(lines[0]!).map((h) => h.trim().toLowerCase());
  const tickerIndex = header.indexOf("ticker");
  const quantityIndex = header.indexOf("quantity");
  const costIndex = header.indexOf("cost_basis");

  const problems: string[] = [];
  if (tickerIndex === -1) problems.push("missing required column: ticker");
  if (quantityIndex === -1) problems.push("missing required column: quantity");
  if (problems.length) throw new CsvError(problems);

  const tickers: string[] = [];
  const quantities: number[] = [];
  const costBasis: number[] = [];
  const seen = new Set<string>();

  for (let i = 1; i < lines.length; i += 1) {
    const fields = splitLine(lines[i]!);
    const rawTicker = (fields[tickerIndex] ?? "").trim().toUpperCase();
    if (!rawTicker) continue;

    if (!TICKER.test(rawTicker)) {
      problems.push(`line ${i + 1}: "${rawTicker}" is not a valid ticker symbol`);
      continue;
    }
    if (seen.has(rawTicker)) {
      problems.push(`line ${i + 1}: ${rawTicker} appears more than once; combine the rows`);
      continue;
    }

    const quantity = Number((fields[quantityIndex] ?? "").trim().replace(/,/g, ""));
    if (!Number.isFinite(quantity)) {
      problems.push(`line ${i + 1}: quantity is not a number`);
      continue;
    }
    if (quantity < 0) {
      problems.push(`line ${i + 1}: negative quantity (short positions are not supported)`);
      continue;
    }

    seen.add(rawTicker);
    tickers.push(rawTicker);
    quantities.push(quantity);

    if (costIndex !== -1) {
      const raw = (fields[costIndex] ?? "").trim().replace(/,/g, "");
      const cost = raw === "" ? 0 : Number(raw);
      if (!Number.isFinite(cost)) {
        problems.push(`line ${i + 1}: cost_basis is not a number`);
        continue;
      }
      costBasis.push(cost);
    }
  }

  if (tickers.length === 0) problems.push("no valid rows found");
  // Report every problem at once -- a user fixing a file should not have to
  // resubmit once per error.
  if (problems.length) throw new CsvError(problems);

  return {
    tickers,
    quantities,
    costBasis: costIndex !== -1 && costBasis.length === tickers.length ? costBasis : null,
  };
}

export const SAMPLE_CSV = `ticker,quantity,cost_basis
AAPL,120,168.40
MSFT,85,352.10
NVDA,40,102.75
JNJ,210,151.20
XOM,160,104.55
JPM,95,178.30
BRK.B,14,398.60
UNH,30,486.10
`;
