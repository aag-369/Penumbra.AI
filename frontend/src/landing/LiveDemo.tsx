/**
 * The live encryption demo (section 03). Loaded as its own chunk when the
 * visitor scrolls near it; `LandingPage` renders the section and its heading.
 *
 * Four tabs, one real pipeline. Keys are generated in this tab, the portfolio is
 * encrypted under them, a public-key-only "server" engine computes on the
 * ciphertexts, and the results are decrypted here and checked against a
 * plaintext computation. Every figure is measured on the visitor's machine.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { bytes, money, ms, percent, sci } from "../lib/format";
import { lookup } from "../lib/market";
import {
  createKeySession,
  decryptResults,
  DEMO_PRICES,
  DEMO_SHARES,
  DEMO_TICKERS,
  encryptHoldings,
  holdingsFor,
  loadSealTimed,
  nextPaint,
  recommend,
  runServer,
  type Decrypted,
  type Encrypted,
  type KeySession,
  type ServerRun,
} from "./demoEngine";
import { Reveal } from "./effects";
import { ArrowRight, CheckIcon, CrossIcon, PlayIcon, ResetIcon } from "./icons";
import { Chip, Spinner } from "./parts";

type StepState = "pending" | "active" | "done" | "reused";
type Busy = null | "encrypt" | "server" | "decrypt";

const TABS = ["Encrypt", "Server Compute", "Decrypt", "Results"] as const;

/** What a clean run of the depth-2 pipeline should stay under (docs/ARCHITECTURE.md). */
const TOLERANCE = 1e-4;

// -- small pieces -----------------------------------------------------------------

function StepLine({
  state,
  label,
  detail,
  timing,
}: {
  state: StepState;
  label: string;
  detail?: string;
  timing?: string;
}) {
  return (
    <li className="flex items-start gap-3 py-1.5">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center">
        {state === "active" ? (
          <Spinner className="h-4 w-4 text-brand-cipher" />
        ) : state === "done" ? (
          <CheckIcon size={18} className="text-brand-ok" />
        ) : state === "reused" ? (
          <CheckIcon size={18} className="text-brand-gray" />
        ) : (
          <span className="h-2 w-2 rounded-full border border-brand-gray/60" />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className={state === "pending" ? "text-brand-gray" : "text-brand-mist"}>{label}</span>
        {detail && <span className="block text-xs text-brand-gray">{detail}</span>}
      </span>
      {timing && <span className="lp-code shrink-0 text-brand-cloud">{timing}</span>}
    </li>
  );
}

function CiphertextView({ ciphertext, size, keyId }: { ciphertext: string; size: number; keyId: string }) {
  const [prefix, id, ...rest] = ciphertext.split(".");
  const body = rest.join(".");
  return (
    <figure className="overflow-hidden rounded-lg border border-brand-cipher/20 bg-brand-abyss">
      <figcaption className="flex flex-wrap items-center justify-between gap-2 border-b border-white/5 px-4 py-2.5 text-xs text-brand-gray">
        <span>Your holdings ciphertext · first 420 characters</span>
        <span className="lp-code text-brand-cloud">{bytes(size)}</span>
      </figcaption>
      <p
        className="lp-code break-all px-4 py-3 text-[12px] leading-relaxed"
        aria-label={`Ciphertext under key ${keyId}, ${bytes(size)}`}
      >
        <span className="text-brand-gray">{prefix}.</span>
        <span className="text-brand-umbra-light">{id}</span>
        <span className="text-brand-gray">.</span>
        <span className="text-sky-400/80">
          {body.slice(0, 420 - (prefix?.length ?? 0) - (id?.length ?? 0) - 2)}
        </span>
        <span className="text-brand-gray">…</span>
      </p>
    </figure>
  );
}

function ErrorNote({ message }: { message: string }) {
  return (
    <p
      role="alert"
      className="mt-4 rounded-lg border border-brand-bad/40 bg-brand-bad/10 px-4 py-3 text-sm text-red-200"
    >
      {message}
    </p>
  );
}

function NeedsStep({ step, onGo }: { step: number; onGo: () => void }) {
  return (
    <p className="mt-4 flex flex-wrap items-center gap-2 text-sm text-brand-gray">
      Complete step {step} first.
      <button
        type="button"
        onClick={onGo}
        className="font-semibold text-brand-cipher underline-offset-4 hover:underline"
      >
        Go to step {step} →
      </button>
    </p>
  );
}

function NextButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="lp-btn-secondary mt-5 px-5 py-2.5 text-sm">
      {label} <ArrowRight size={16} />
    </button>
  );
}

function StatTile({
  label,
  value,
  sub,
  accent,
  tag,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  accent: string;
  tag?: ReactNode;
}) {
  return (
    <div className="relative overflow-hidden rounded-lg border border-white/[0.06] bg-brand-abyss/80 p-5">
      <span aria-hidden="true" className={`absolute inset-x-0 top-0 h-0.5 ${accent}`} />
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-brand-gray">{label}</p>
        {tag}
      </div>
      <p className="mt-2 text-2xl font-bold tracking-tight text-brand-mist">{value}</p>
      {sub && <p className="mt-1.5 text-xs leading-relaxed text-brand-gray">{sub}</p>}
    </div>
  );
}

// -- the demo ---------------------------------------------------------------------

export default function LiveDemo() {
  const [tab, setTab] = useState(0);
  const [shares, setShares] = useState<number[]>(DEMO_SHARES);
  const [session, setSession] = useState<KeySession | null>(null);
  const [encrypted, setEncrypted] = useState<Encrypted | null>(null);
  const [server, setServer] = useState<ServerRun | null>(null);
  const [decrypted, setDecrypted] = useState<Decrypted | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<{ step: number; message: string } | null>(null);
  const [progress, setProgress] = useState<{
    seal: StepState;
    keys: StepState;
    encrypt: StepState;
    sealMs?: number;
    sealCached?: boolean;
  }>({
    seal: "pending",
    keys: "pending",
    encrypt: "pending",
  });
  const [shownOps, setShownOps] = useState(0);
  const [announce, setAnnounce] = useState("");
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const sessionRef = useRef<KeySession | null>(null);

  const holdings = useMemo(() => holdingsFor(shares), [shares]);
  const recommendation = useMemo(
    () => (encrypted && decrypted ? recommend(encrypted, decrypted) : null),
    [encrypted, decrypted],
  );
  const done = [encrypted !== null, server !== null, decrypted !== null, decrypted !== null];

  // Reveal the server's console lines one at a time. Timings are real; only the
  // pacing of the reveal is presentation.
  useEffect(() => {
    if (!server) {
      setShownOps(0);
      return;
    }
    setShownOps(0);
    let n = 0;
    const timer = window.setInterval(() => {
      n += 1;
      setShownOps(n);
      if (n >= 6) window.clearInterval(timer);
    }, 170);
    return () => window.clearInterval(timer);
  }, [server]);

  const invalidateFrom = useCallback((step: number) => {
    if (step <= 1) setEncrypted(null);
    if (step <= 2) setServer(null);
    if (step <= 3) setDecrypted(null);
  }, []);

  function setShare(index: number, raw: string) {
    const parsed = Math.floor(Number(raw));
    const value = Number.isFinite(parsed) ? Math.min(Math.max(parsed, 0), 100_000) : 0;
    setShares((prev) => prev.map((q, i) => (i === index ? value : q)));
    invalidateFrom(1);
    setProgress((p) => ({ ...p, encrypt: "pending" }));
  }

  // -- steps ----------------------------------------------------------------------

  const doEncrypt = useCallback(async (): Promise<Encrypted | null> => {
    setBusy("encrypt");
    setError(null);
    invalidateFrom(1);
    try {
      let current = sessionRef.current;
      if (!current) {
        setProgress({ seal: "active", keys: "pending", encrypt: "pending" });
        await nextPaint();
        const seal = await loadSealTimed();
        setProgress({
          seal: "done",
          keys: "active",
          encrypt: "pending",
          sealMs: seal.ms,
          sealCached: seal.cached,
        });
        await nextPaint();
        current = await createKeySession(seal);
        sessionRef.current = current;
        setSession(current);
      } else {
        setProgress((p) => ({ ...p, seal: p.seal === "done" ? "done" : "reused", keys: "reused" }));
      }
      setProgress((p) => ({ ...p, keys: p.keys === "reused" ? "reused" : "done", encrypt: "active" }));
      await nextPaint();
      const result = encryptHoldings(current, holdingsFor(shares));
      setEncrypted(result);
      setProgress((p) => ({ ...p, encrypt: "done" }));
      setAnnounce(
        `Encrypted ${shares.length} holdings into two ciphertexts of ${bytes(result.sharesBytes)} each.`,
      );
      return result;
    } catch (cause) {
      setError({ step: 0, message: cause instanceof Error ? cause.message : String(cause) });
      setProgress((p) => ({
        seal: p.seal === "active" ? "pending" : p.seal,
        keys: p.keys === "active" ? "pending" : p.keys,
        encrypt: "pending",
      }));
      return null;
    } finally {
      setBusy(null);
    }
  }, [invalidateFrom, shares]);

  const doServer = useCallback(
    async (enc: Encrypted | null = encrypted): Promise<ServerRun | null> => {
      const current = sessionRef.current;
      if (!current || !enc) return null;
      setBusy("server");
      setError(null);
      invalidateFrom(2);
      try {
        await nextPaint();
        const run = await runServer(current, enc);
        setServer(run);
        setAnnounce(`Server computed three encrypted results in ${ms(run.computeMs)} without decrypting.`);
        return run;
      } catch (cause) {
        setError({ step: 1, message: cause instanceof Error ? cause.message : String(cause) });
        return null;
      } finally {
        setBusy(null);
      }
    },
    [encrypted, invalidateFrom],
  );

  const doDecrypt = useCallback(
    async (enc: Encrypted | null = encrypted, run: ServerRun | null = server): Promise<Decrypted | null> => {
      const current = sessionRef.current;
      if (!current || !enc || !run) return null;
      setBusy("decrypt");
      setError(null);
      try {
        await nextPaint();
        const result = decryptResults(current, enc, run);
        setDecrypted(result);
        setAnnounce(`Decrypted. Worst relative error ${sci(result.worstError)}.`);
        return result;
      } catch (cause) {
        setError({ step: 2, message: cause instanceof Error ? cause.message : String(cause) });
        return null;
      } finally {
        setBusy(null);
      }
    },
    [encrypted, server],
  );

  const [runningAll, setRunningAll] = useState(false);
  async function runAll() {
    setRunningAll(true);
    try {
      setTab(0);
      const enc = await doEncrypt();
      if (!enc) return;
      await new Promise((r) => setTimeout(r, 500));
      setTab(1);
      const run = await doServer(enc);
      if (!run) return;
      await new Promise((r) => setTimeout(r, 1400));
      setTab(2);
      const dec = await doDecrypt(enc, run);
      if (!dec) return;
      await new Promise((r) => setTimeout(r, 900));
      setTab(3);
    } finally {
      setRunningAll(false);
    }
  }

  function reset() {
    setShares(DEMO_SHARES);
    invalidateFrom(1);
    setError(null);
    setProgress((p) => ({ ...p, encrypt: "pending" }));
    setTab(0);
  }

  // -- tabs keyboard ----------------------------------------------------------------

  function onTabKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number | null = null;
    if (event.key === "ArrowRight") next = (index + 1) % TABS.length;
    if (event.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = TABS.length - 1;
    if (next === null) return;
    event.preventDefault();
    setTab(next);
    tabRefs.current[next]?.focus();
  }

  const metrics = session?.metrics ?? null;
  const locked = busy !== null || runningAll;

  // -- render -----------------------------------------------------------------------

  return (
    <>
      <div className="relative mx-auto max-w-4xl">
        <Reveal>
          <div className="lp-glass lp-border-cipher p-5 sm:p-8">
            <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div
                role="tablist"
                aria-label="Demo steps"
                className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap"
              >
                {TABS.map((name, index) => {
                  const selected = tab === index;
                  return (
                    <button
                      key={name}
                      ref={(el) => {
                        tabRefs.current[index] = el;
                      }}
                      role="tab"
                      id={`demo-tab-${index}`}
                      aria-selected={selected}
                      aria-controls={`demo-panel-${index}`}
                      tabIndex={selected ? 0 : -1}
                      onClick={() => setTab(index)}
                      onKeyDown={(e) => onTabKey(e, index)}
                      className={`inline-flex min-h-[44px] items-center justify-center gap-2 rounded px-4 py-2 text-sm font-semibold transition-colors duration-300 ${
                        selected
                          ? "bg-brand-cipher text-brand-ink"
                          : "border border-brand-cipher text-brand-cipher hover:bg-brand-cipher/10"
                      }`}
                    >
                      {done[index] ? <CheckIcon size={16} /> : null}
                      {index + 1}. {name}
                    </button>
                  );
                })}
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => void runAll()}
                  disabled={locked}
                  className="lp-btn-primary min-h-[44px] flex-1 px-4 py-2 text-sm lg:flex-none"
                >
                  {runningAll ? <Spinner className="h-4 w-4" /> : <PlayIcon size={14} />}
                  {runningAll ? "Running…" : "Run full pipeline"}
                </button>
                <button
                  type="button"
                  onClick={reset}
                  disabled={locked}
                  aria-label="Reset the demo"
                  title="Reset share counts"
                  className="lp-btn-secondary min-h-[44px] px-3"
                >
                  <ResetIcon size={18} />
                </button>
              </div>
            </div>

            {/* 1 · encrypt */}
            <div
              role="tabpanel"
              id="demo-panel-0"
              aria-labelledby="demo-tab-0"
              hidden={tab !== 0}
              className="lp-fade-in"
            >
              <h3 className="text-xl font-bold text-brand-mist">Step 1: Encrypt Your Portfolio</h3>
              <p className="mt-2 text-brand-cloud">
                Sample portfolio of 8 stocks. Edit any share count, then encrypt with CKKS:
              </p>

              <div className="mt-5 overflow-hidden rounded-lg border border-white/[0.06] bg-brand-slate/60">
                <div className="lp-code grid grid-cols-[1fr_96px_1fr] gap-x-3 border-b border-white/[0.06] px-4 py-2.5 text-xs uppercase tracking-wider text-brand-gray sm:grid-cols-[1.2fr_110px_1fr_1fr]">
                  <span>Ticker</span>
                  <span>Shares</span>
                  <span className="hidden text-right sm:block">Price</span>
                  <span className="text-right">Value</span>
                </div>
                <ul>
                  {DEMO_TICKERS.map((ticker, i) => (
                    <li
                      key={ticker}
                      className="lp-code grid grid-cols-[1fr_96px_1fr] items-center gap-x-3 border-b border-white/[0.04] px-4 py-1.5 last:border-b-0 sm:grid-cols-[1.2fr_110px_1fr_1fr]"
                    >
                      <span className="truncate">
                        <span className="font-semibold text-brand-mist">{ticker}</span>
                        <span className="ml-2 hidden font-sans text-xs text-brand-gray md:inline">
                          {lookup(ticker)?.name}
                        </span>
                      </span>
                      <label className="sr-only" htmlFor={`shares-${i}`}>
                        Shares of {ticker}
                      </label>
                      <input
                        id={`shares-${i}`}
                        type="number"
                        inputMode="numeric"
                        min={0}
                        max={100000}
                        step={1}
                        value={shares[i]}
                        disabled={locked}
                        onChange={(e) => setShare(i, e.target.value)}
                        className="h-9 w-full rounded-md border border-brand-cipher/20 bg-brand-ink px-2.5 text-brand-mist transition-colors focus:border-brand-cipher disabled:opacity-60"
                      />
                      <span className="hidden text-right text-brand-gray sm:block">
                        {money(DEMO_PRICES[i]!)}
                      </span>
                      <span className="text-right text-brand-cloud">{money(holdings.values[i]!)}</span>
                    </li>
                  ))}
                </ul>
                <div className="lp-code flex items-center justify-between border-t border-white/[0.06] bg-brand-ink/60 px-4 py-2.5">
                  <span className="text-brand-gray">Total</span>
                  <span className="font-semibold text-brand-mist">{money(holdings.total)}</span>
                </div>
              </div>
              <p className="mt-2 text-xs text-brand-gray">
                Prices and return estimates are the app's fixed illustrative market model, not live quotes.
              </p>

              <button
                type="button"
                onClick={() => void doEncrypt()}
                disabled={locked || holdings.total <= 0}
                className="lp-btn-primary mt-5 min-h-[48px] w-full px-6 py-3"
              >
                {busy === "encrypt" ? <Spinner /> : null}
                {busy === "encrypt" ? "Encrypting…" : encrypted ? "Encrypt Again" : "Encrypt Now"}
              </button>

              {(progress.seal !== "pending" || encrypted) && (
                <ul
                  className="mt-5 rounded-lg border border-white/[0.06] bg-brand-abyss/80 px-4 py-2 text-sm"
                  aria-label="Encryption progress"
                >
                  <StepLine
                    state={progress.seal}
                    label="Load Microsoft SEAL (WebAssembly)"
                    detail={progress.sealCached ? "already in memory" : "1.4 MB module, loaded on demand"}
                    timing={
                      progress.seal === "done" && progress.sealMs !== undefined
                        ? ms(progress.sealMs)
                        : undefined
                    }
                  />
                  <StepLine
                    state={progress.keys}
                    label="Generate keypair and rotation keys · N = 8192"
                    detail={
                      metrics
                        ? `secret key ${bytes(metrics.secretKeyBytes)} stays here · rotation keys ${bytes(metrics.rotationKeyBytes)}`
                        : progress.keys === "active"
                          ? "the heavy part — your tab may pause for a moment"
                          : undefined
                    }
                    timing={
                      metrics && progress.keys === "done"
                        ? ms(metrics.keygenMs + metrics.rotationKeygenMs)
                        : progress.keys === "reused"
                          ? "reused"
                          : undefined
                    }
                  />
                  <StepLine
                    state={progress.encrypt}
                    label="Encrypt share counts and weights"
                    detail="periodic packing: 8 values repeated across 4,096 slots · weights in percentage points"
                    timing={encrypted && progress.encrypt === "done" ? ms(encrypted.encryptMs) : undefined}
                  />
                </ul>
              )}

              {error?.step === 0 && <ErrorNote message={error.message} />}

              {encrypted && session && (
                <div className="lp-fade-in mt-5 space-y-4">
                  <ul className="lp-code space-y-1 text-sm text-brand-ok">
                    <li>✓ Encrypted {DEMO_TICKERS.length} holdings with CKKS into 2 ciphertexts</li>
                    <li>
                      ✓ Ciphertext size: {bytes(encrypted.sharesBytes)} each · {encrypted.levels} of 2 levels
                      unused
                    </li>
                    <li>✓ Encryption time: {ms(encrypted.encryptMs)}</li>
                  </ul>
                  <CiphertextView
                    ciphertext={encrypted.sharesCt}
                    size={encrypted.sharesBytes}
                    keyId={session.client.keyId}
                  />
                  {!runningAll && <NextButton label="Continue to server compute" onClick={() => setTab(1)} />}
                </div>
              )}
            </div>

            {/* 2 · server */}
            <div
              role="tabpanel"
              id="demo-panel-1"
              aria-labelledby="demo-tab-1"
              hidden={tab !== 1}
              className="lp-fade-in"
            >
              <h3 className="text-xl font-bold text-brand-mist">
                Step 2: Server-Side Homomorphic Computation
              </h3>
              <p className="mt-2 text-brand-cloud">
                The server's engine is rebuilt from your public bundle alone. It computes on your ciphertexts
                — and cannot open them:
              </p>

              <ServerConsole run={server} shown={shownOps} running={busy === "server"} />

              {!encrypted ? (
                <NeedsStep step={1} onGo={() => setTab(0)} />
              ) : (
                <button
                  type="button"
                  onClick={() => void doServer()}
                  disabled={locked}
                  className="lp-btn-primary mt-5 min-h-[48px] w-full px-6 py-3"
                >
                  {busy === "server" ? <Spinner /> : null}
                  {busy === "server"
                    ? "Computing on ciphertext…"
                    : server
                      ? "Run Computation Again"
                      : "Run Computation"}
                </button>
              )}
              {error?.step === 1 && <ErrorNote message={error.message} />}
              {server && shownOps >= 6 && !runningAll && (
                <NextButton label="Continue to decryption" onClick={() => setTab(2)} />
              )}
            </div>

            {/* 3 · decrypt */}
            <div
              role="tabpanel"
              id="demo-panel-2"
              aria-labelledby="demo-tab-2"
              hidden={tab !== 2}
              className="lp-fade-in"
            >
              <h3 className="text-xl font-bold text-brand-mist">Step 3: Decrypt in Browser</h3>
              <p className="mt-2 text-brand-cloud">
                The results arrive encrypted. Only the secret key in this tab can unlock them:
              </p>

              <dl className="lp-code mt-5 grid gap-x-6 gap-y-2 rounded-lg border border-white/[0.06] bg-brand-abyss/80 p-4 text-sm sm:grid-cols-[auto_1fr]">
                <dt className="text-brand-gray">Result ciphertexts</dt>
                <dd className="text-brand-cloud">
                  {server ? `3 · ${bytes(server.resultBytes)} total` : "—"}
                </dd>
                <dt className="text-brand-gray">Your secret key</dt>
                <dd className="text-brand-cloud">
                  <span aria-hidden="true" className="tracking-[0.2em] text-brand-umbra-light">
                    ●●●●●●●●
                  </span>{" "}
                  {metrics ? `${bytes(metrics.secretKeyBytes)} · 0 bytes sent` : "not generated yet"}
                </dd>
                <dt className="text-brand-gray">Key id</dt>
                <dd className="break-all text-brand-umbra-light">
                  {session ? `pnb1.${session.client.keyId}` : "—"}
                </dd>
              </dl>

              {!server ? (
                <NeedsStep step={encrypted ? 2 : 1} onGo={() => setTab(encrypted ? 1 : 0)} />
              ) : (
                <button
                  type="button"
                  onClick={() => void doDecrypt()}
                  disabled={locked}
                  className="lp-btn-primary mt-5 min-h-[48px] w-full px-6 py-3"
                >
                  {busy === "decrypt" ? <Spinner /> : null}
                  {decrypted ? "Decrypt Again" : "Decrypt Results"}
                </button>
              )}
              {error?.step === 2 && <ErrorNote message={error.message} />}

              {decrypted && (
                <div className="lp-fade-in mt-5">
                  <div className="overflow-x-auto rounded-lg border border-white/[0.06]">
                    <table className="w-full min-w-[520px] text-left text-sm">
                      <caption className="sr-only">Decrypted results checked against plaintext</caption>
                      <thead className="bg-brand-slate/60 text-xs uppercase tracking-wider text-brand-gray">
                        <tr>
                          <th scope="col" className="px-4 py-2.5 font-medium">
                            Result
                          </th>
                          <th scope="col" className="px-4 py-2.5 text-right font-medium">
                            From ciphertext
                          </th>
                          <th scope="col" className="px-4 py-2.5 text-right font-medium">
                            Plaintext check
                          </th>
                          <th scope="col" className="px-4 py-2.5 text-right font-medium">
                            Rel. error
                          </th>
                        </tr>
                      </thead>
                      <tbody className="lp-code">
                        {[
                          [
                            "Portfolio value",
                            money(decrypted.value),
                            money(decrypted.truth.value),
                            decrypted.errors.value,
                          ],
                          [
                            "Expected return",
                            percent(decrypted.ret, 3),
                            percent(decrypted.truth.ret, 3),
                            decrypted.errors.ret,
                          ],
                          [
                            "Variance w⊤Σw",
                            decrypted.variance.toFixed(6),
                            decrypted.truth.variance.toFixed(6),
                            decrypted.errors.variance,
                          ],
                        ].map(([label, got, want, err]) => (
                          <tr key={label as string} className="border-t border-white/[0.05]">
                            <th scope="row" className="px-4 py-2.5 font-sans font-medium text-brand-mist">
                              {label}
                            </th>
                            <td className="px-4 py-2.5 text-right text-brand-mist">{got}</td>
                            <td className="px-4 py-2.5 text-right text-brand-gray">{want}</td>
                            <td className="px-4 py-2.5 text-right text-emerald-300">{sci(err as number)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <ul className="lp-code mt-4 space-y-1 text-sm text-brand-ok">
                    <li>✓ Decrypted with your secret key in {ms(decrypted.decryptMs)}</li>
                    <li>
                      ✓ Worst relative error {sci(decrypted.worstError)} —{" "}
                      {decrypted.worstError < TOLERANCE ? "within" : "outside"} CKKS tolerance
                    </li>
                  </ul>
                  {!runningAll && <NextButton label="See your results" onClick={() => setTab(3)} />}
                </div>
              )}
            </div>

            {/* 4 · results */}
            <div
              role="tabpanel"
              id="demo-panel-3"
              aria-labelledby="demo-tab-3"
              hidden={tab !== 3}
              className="lp-fade-in"
            >
              <h3 className="text-xl font-bold text-brand-mist">Step 4: Your Recommendations</h3>
              {!decrypted || !recommendation ? (
                <>
                  <p className="mt-2 text-brand-cloud">
                    Run steps 1–3 and your measured results appear here.
                  </p>
                  <div className="mt-5 grid gap-4 sm:grid-cols-2" aria-hidden="true">
                    {["Recommended allocation", "Expected return", "Volatility", "Precision"].map((label) => (
                      <div
                        key={label}
                        className="rounded-lg border border-white/[0.06] bg-brand-abyss/80 p-5"
                      >
                        <p className="text-sm text-brand-gray">{label}</p>
                        <div className="lp-shimmer mt-3 h-7 w-2/3 rounded bg-white/[0.04]" />
                      </div>
                    ))}
                  </div>
                  <button
                    type="button"
                    onClick={() => void runAll()}
                    disabled={locked}
                    className="lp-btn-primary mt-5 min-h-[48px] w-full px-6 py-3"
                  >
                    <PlayIcon size={14} /> Run the full pipeline
                  </button>
                </>
              ) : (
                <>
                  <p className="mt-2 text-brand-cloud">
                    Your current portfolio's risk and return, computed on ciphertext and decrypted here — and
                    the rebalance the optimizer suggests.
                  </p>
                  <div className="mt-5 grid gap-4 sm:grid-cols-2">
                    <StatTile
                      label="Recommended allocation"
                      accent="bg-brand-cipher"
                      value={<span className="text-sky-300">{recommendation.trades} trades</span>}
                      sub={`Volatility ${percent(decrypted.volatility, 1)} → ${percent(recommendation.targetVolatility, 1)} · return ${percent(decrypted.ret, 1)} → ${percent(recommendation.targetReturn, 1)} · turnover ${percent(recommendation.turnover, 0)}`}
                    />
                    <StatTile
                      label="Expected return"
                      accent="bg-brand-umbra"
                      value={
                        <span className="text-brand-umbra-light">{percent(decrypted.ret, 1)} annual</span>
                      }
                      sub="Current portfolio, from ciphertext"
                    />
                    <StatTile
                      label="Volatility"
                      accent="bg-brand-ok"
                      value={percent(decrypted.volatility, 1)}
                      sub="√(w⊤Σw), evaluated at depth 2"
                    />
                    <StatTile
                      label="Precision"
                      accent="bg-brand-warn"
                      value={sci(decrypted.worstError)}
                      sub="Worst relative error of the three results"
                      tag={
                        decrypted.worstError < TOLERANCE ? (
                          <Chip tone="ok">
                            <CheckIcon size={12} /> within tolerance
                          </Chip>
                        ) : (
                          <Chip tone="warn">check</Chip>
                        )
                      }
                    />
                  </div>

                  {recommendation.moves.length > 0 && (
                    <div className="mt-5">
                      <p className="text-sm text-brand-gray">Largest moves</p>
                      <ul className="mt-2 flex flex-wrap gap-2">
                        {recommendation.moves.map((move) => (
                          <li key={move.ticker}>
                            <Chip tone={move.side === "BUY" ? "cipher" : "umbra"}>
                              <span className="lp-code">{move.side}</span> {move.ticker}{" "}
                              <span className="lp-code">
                                {move.deltaWeight > 0 ? "+" : "−"}
                                {percent(Math.abs(move.deltaWeight), 1)}
                              </span>
                            </Chip>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <p className="mt-5 text-xs leading-relaxed text-brand-gray">
                    The optimizer is the app's mean-variance solver (λ ={" "}
                    {recommendation.riskAversion.toFixed(2)}, 35% position cap), running on this device; the
                    server-side QAOA path is Phase 4. Market figures are illustrative.
                  </p>
                  <button
                    type="button"
                    onClick={() => setTab(0)}
                    className="lp-btn-secondary mt-5 px-5 py-2.5 text-sm"
                  >
                    Change share counts and run again <ArrowRight size={16} />
                  </button>
                </>
              )}
            </div>
          </div>
        </Reveal>

        <p aria-live="polite" className="sr-only">
          {announce}
        </p>

        <DemoMetrics session={session} server={server} />

        <p className="mx-auto mt-6 max-w-3xl text-center text-xs leading-relaxed text-brand-gray">
          The "server" in this demo is a second engine in your tab, built only from your public bundle — the
          same object the API constructs, with no decryptor at all. The Python backend runs the TenSEAL twin
          of these operations under 265 tests; sending browser ciphertexts to it is Phase 6 (wire-format
          interop).
        </p>
      </div>
    </>
  );
}

// -- server console -----------------------------------------------------------------

function ServerConsole({ run, shown, running }: { run: ServerRun | null; shown: number; running: boolean }) {
  const planned: { key: string; code: string; note: string }[] = [
    { key: "build", code: "server = CkksEngine.fromPublicBundle(bundle)", note: "evaluation keys only" },
    { key: "decrypt", code: "server.decrypt(holdings)", note: "the attempt the whole design rests on" },
    { key: "value", code: "value  = Σ qᵢ·pᵢ", note: "share counts × public prices" },
    { key: "return", code: "return = μ⊤w", note: "weights × public mean returns" },
    { key: "risk", code: "risk   = w⊤Σw", note: "the Markowitz risk term" },
  ];

  return (
    <div className="lp-code mt-5 overflow-hidden rounded-lg border border-brand-cipher/15 bg-brand-abyss text-[13px]">
      <div className="flex items-center gap-2 border-b border-white/5 px-4 py-2 text-xs text-brand-gray">
        <span className="h-2.5 w-2.5 rounded-full bg-brand-umbra/70" aria-hidden="true" />
        server role · public keys only
        {running && <Spinner className="ml-auto h-3.5 w-3.5 text-brand-cipher" />}
      </div>
      <ol className="space-y-2.5 px-4 py-4">
        {planned.map((line, index) => {
          const revealed = run !== null && shown > index;
          const op = run?.ops.find((o) => o.id === line.key);
          const isRefusal = line.key === "decrypt";
          return (
            <li
              key={line.key}
              className={`flex flex-wrap items-start gap-x-3 gap-y-1 transition-opacity duration-300 ${revealed ? "opacity-100" : "opacity-45"}`}
            >
              <span className="w-4 shrink-0 pt-px" aria-hidden="true">
                {!revealed ? (
                  <span className="text-brand-gray">○</span>
                ) : isRefusal ? (
                  <CrossIcon size={15} className="text-red-400" />
                ) : (
                  <CheckIcon size={15} className="text-brand-ok" />
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span
                  className={revealed ? (isRefusal ? "text-red-300" : "text-sky-300") : "text-brand-gray"}
                >
                  {line.code}
                </span>
                <span className="block text-xs text-brand-gray">
                  {!revealed || !run
                    ? line.note
                    : line.key === "build"
                      ? `${bytes(run.bundleBytes)} of public, relinearization and rotation keys · no secret key`
                      : isRefusal
                        ? `refused: ${run.refusal.replace(" -- ", " — ")}`
                        : `${op?.detail} · ${op?.levelsLeft} level${op?.levelsLeft === 1 ? "" : "s"} left`}
                </span>
              </span>
              {revealed && run && (
                <span className="shrink-0 text-brand-cloud">
                  {line.key === "build"
                    ? run.reusedServer
                      ? "reused"
                      : ms(run.serverBuildMs)
                    : op
                      ? ms(op.ms)
                      : isRefusal
                        ? "blocked"
                        : ""}
                </span>
              )}
            </li>
          );
        })}
        {run && shown >= 6 && (
          <li className="lp-fade-in flex gap-3 border-t border-white/5 pt-3 text-brand-ok">
            <span className="w-4 shrink-0" aria-hidden="true">
              →
            </span>
            <span>
              3 encrypted results · {bytes(run.resultBytes)} · computed in {ms(run.computeMs)} · returned to
              the client
            </span>
          </li>
        )}
      </ol>
    </div>
  );
}

// -- metrics row --------------------------------------------------------------------

function DemoMetrics({ session, server }: { session: KeySession | null; server: ServerRun | null }) {
  const measured = <Chip tone="ok">measured here</Chip>;
  const reference = <Chip tone="neutral">reference</Chip>;
  const m = session?.metrics;
  const cards = [
    {
      label: "Encryption Overhead",
      value: m ? bytes(m.rotationKeyBytes) : "≈ 32 MB",
      tone: "text-sky-300",
      sub: "Rotation keys — mandatory for every encrypted reduction",
      tag: m ? measured : reference,
    },
    {
      label: "Computation Time",
      value: server ? ms(server.computeMs) : "< 1 s",
      tone: "text-brand-umbra-light",
      sub: "Server-side: value, return and w⊤Σw on ciphertext",
      tag: server ? measured : reference,
    },
    {
      label: "Security Level",
      value: "128-bit",
      tone: "text-emerald-300",
      sub: "N = 8192 · 200 of 218 modulus bits · Ring-LWE",
      tag: <Chip tone="neutral">enforced</Chip>,
    },
  ];
  return (
    <ul className="mt-8 grid gap-4 sm:grid-cols-3">
      {cards.map((card, index) => (
        <Reveal key={card.label} as="li" delay={index * 50}>
          <div className="lp-glass h-full p-6 text-center">
            <div className="flex justify-center">{card.tag}</div>
            <p className="mt-3 text-sm text-brand-gray">{card.label}</p>
            <p className={`mt-1 text-3xl font-bold tracking-tight ${card.tone}`}>{card.value}</p>
            <p className="mt-2 text-xs leading-relaxed text-brand-gray">{card.sub}</p>
          </div>
        </Reveal>
      ))}
    </ul>
  );
}
