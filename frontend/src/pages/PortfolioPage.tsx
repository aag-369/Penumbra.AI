import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Alert, Button, CiphertextBlock, EmptyState, KeyValue, Panel, Stat } from "../components/ui";
import { CsvError, parsePortfolioCsv, SAMPLE_CSV, type ParsedPortfolio } from "../lib/csv";
import { bytes, money, ms, num } from "../lib/format";
import { demoBackend } from "../lib/demoBackend";
import { lookup, pricesFor } from "../lib/market";
import { useApp } from "../store/AppContext";

type Stage = "idle" | "parsed" | "encrypting" | "uploaded";

export default function PortfolioPage() {
  const { engine, keyState, setPortfolio, portfolio } = useApp();
  const navigate = useNavigate();
  const fileInput = useRef<HTMLInputElement>(null);

  const [stage, setStage] = useState<Stage>("idle");
  const [parsed, setParsed] = useState<ParsedPortfolio | null>(null);
  const [ciphertext, setCiphertext] = useState<string | null>(null);
  const [encryptMs, setEncryptMs] = useState(0);
  const [problems, setProblems] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  function ingest(text: string) {
    setError(null);
    setProblems([]);
    try {
      const result = parsePortfolioCsv(text);
      setParsed(result);
      setStage("parsed");
      setCiphertext(null);
    } catch (cause) {
      if (cause instanceof CsvError) setProblems(cause.problems);
      else setError(cause instanceof Error ? cause.message : "could not read that file");
      setParsed(null);
      setStage("idle");
    }
  }

  async function onFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) ingest(await file.text());
  }

  async function encryptAndUpload() {
    if (!engine || !parsed) return;
    setStage("encrypting");
    setError(null);
    try {
      const started = performance.now();
      const holdingsCiphertext = engine.encrypt(parsed.quantities);
      const costCiphertext = parsed.costBasis ? engine.encrypt(parsed.costBasis) : null;
      const elapsed = performance.now() - started;

      const record = await demoBackend.uploadPortfolio({
        name: "My Portfolio",
        tickers: parsed.tickers,
        holdingsCiphertext,
        costBasisCiphertext: costCiphertext,
      });

      setCiphertext(holdingsCiphertext);
      setEncryptMs(elapsed);
      setPortfolio(record, parsed.quantities);
      setStage("uploaded");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "encryption failed");
      setStage("parsed");
    }
  }

  if (keyState !== "ready") {
    return (
      <EmptyState
        title="An encryption key is needed first"
        action={<Button onClick={() => navigate("/keys")}>Set up a key</Button>}
      >
        Holdings are encrypted before they are stored, so the key has to exist before there is anything
        to encrypt them with.
      </EmptyState>
    );
  }

  const totalValue = parsed
    ? parsed.quantities.reduce((sum, q, i) => sum + q * (pricesFor(parsed.tickers)[i] ?? 0), 0)
    : 0;

  return (
    <div className="space-y-6 animate-riseIn">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Portfolio</h1>
          <p className="mt-1 text-sm text-mist-dim">
            The file is parsed and encrypted here. Quantities never leave this browser in plaintext.
          </p>
        </div>
        {portfolio && (
          <Button variant="ghost" onClick={() => navigate("/")}>
            View dashboard →
          </Button>
        )}
      </header>

      <div className="grid gap-6 lg:grid-cols-[1fr_1.1fr]">
        <Panel title="Upload holdings" subtitle="CSV with columns: ticker, quantity, cost_basis">
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={async (e) => {
              e.preventDefault();
              const file = e.dataTransfer.files?.[0];
              if (file) ingest(await file.text());
            }}
            className="rounded-lg border border-dashed border-ink-600 px-5 py-8 text-center transition-colors hover:border-umbra/50"
          >
            <p className="text-sm text-mist-dim">Drop a CSV here</p>
            <p className="mt-1 text-xs text-mist-faint">or</p>
            <div className="mt-3 flex flex-wrap justify-center gap-2">
              <Button variant="ghost" onClick={() => fileInput.current?.click()}>
                Choose a file
              </Button>
              <Button variant="quiet" onClick={() => ingest(SAMPLE_CSV)}>
                Use the sample portfolio
              </Button>
            </div>
            <input ref={fileInput} type="file" accept=".csv,text/csv" onChange={onFile} className="hidden" />
          </div>

          {problems.length > 0 && (
            <Alert tone="bad" title="That file could not be read">
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {problems.map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            </Alert>
          )}
          {error && (
            <div className="mt-4">
              <Alert tone="bad">{error}</Alert>
            </div>
          )}

          {parsed && (
            <div className="mt-5 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <Stat label="Assets" value={parsed.tickers.length} />
                <Stat label="Value at sample prices" value={money(totalValue)} sub="computed locally" />
              </div>

              <div className="overflow-hidden rounded-lg border border-ink-700">
                <table className="w-full text-sm">
                  <thead className="bg-ink-900/70 text-[11px] uppercase tracking-wider text-mist-faint">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Ticker</th>
                      <th className="px-3 py-2 text-left font-medium">Name</th>
                      <th className="px-3 py-2 text-right font-medium">Quantity</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-700/70">
                    {parsed.tickers.map((ticker, index) => (
                      <tr key={ticker}>
                        <td className="px-3 py-2 font-mono text-[13px] text-mist">{ticker}</td>
                        <td className="px-3 py-2 text-xs text-mist-faint">{lookup(ticker)?.name ?? "—"}</td>
                        <td className="px-3 py-2 text-right font-mono text-[13px] text-mist">
                          {num(parsed.quantities[index] ?? 0, 0)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <Button onClick={encryptAndUpload} loading={stage === "encrypting"} className="w-full">
                Encrypt and upload
              </Button>
            </div>
          )}
        </Panel>

        <div className="space-y-6">
          <Panel title="What leaves this browser" subtitle="The exact payload the server receives">
            {stage === "uploaded" && ciphertext && parsed ? (
              <div className="space-y-4">
                <KeyValue
                  rows={[
                    ["Tickers", <span key="t" className="text-mist">{parsed.tickers.join(", ")}</span>],
                    ["Asset count", parsed.tickers.length],
                    ["Quantities", <span key="q" className="text-cipher">encrypted</span>],
                    ["Cost basis", parsed.costBasis ? <span key="c" className="text-cipher">encrypted</span> : "not provided"],
                    ["Ciphertext size", bytes(Math.floor((ciphertext.length * 3) / 4))],
                    ["Encryption time", ms(encryptMs)],
                  ]}
                />
                <CiphertextBlock
                  ciphertext={ciphertext}
                  bytes={Math.floor((ciphertext.length * 3) / 4)}
                  label="holdings ciphertext"
                />
                <Alert tone="cipher" title="One ciphertext, not one per ticker">
                  A CKKS ciphertext costs the same whether it carries one value or four thousand — this
                  one has {parsed.tickers.length} of {engine?.slotCount.toLocaleString()} slots used.
                  Storing a ciphertext per ticker, as the original specification did, would have
                  multiplied this by {parsed.tickers.length} for no benefit.
                </Alert>
                <Button onClick={() => navigate("/")} className="w-full">
                  Go to dashboard →
                </Button>
              </div>
            ) : (
              <EmptyState title="Nothing uploaded yet">
                Upload a portfolio and the encrypted payload appears here, byte for byte, before it goes
                anywhere.
              </EmptyState>
            )}
          </Panel>

          <Panel title="Expected format">
            <pre className="overflow-x-auto rounded-lg border border-ink-700 bg-ink-900 p-3.5 font-mono text-[11px] leading-relaxed text-mist-dim">
{`ticker,quantity,cost_basis
AAPL,120,168.40
MSFT,85,352.10
BRK.B,14,398.60`}
            </pre>
            <p className="mt-3 text-xs leading-relaxed text-mist-faint">
              <code className="font-mono text-cipher">cost_basis</code> is optional. Quoted thousands
              separators are handled. Duplicate tickers, negative quantities and malformed symbols are
              rejected with every problem listed at once.
            </p>
          </Panel>
        </div>
      </div>
    </div>
  );
}
