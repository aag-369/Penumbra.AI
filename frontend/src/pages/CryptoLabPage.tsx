/**
 * The demonstration page.
 *
 * Every claim the project makes, executable in front of an examiner. Nothing on
 * this page is precomputed and nothing is faked: the buttons run real CKKS in
 * this tab and print what actually happens, including the failures.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { SizeCompare } from "../components/charts";
import { Alert, Badge, Button, CiphertextBlock, Dot, EmptyState, KeyValue, Panel, Stat } from "../components/ui";
import { bytes, ms, num, sci } from "../lib/format";
import { CkksEngine, DEFAULT_PARAMS } from "../lib/seal";
import { useApp } from "../store/AppContext";

interface LogLine {
  kind: "in" | "out" | "err" | "note";
  text: string;
}

function Console({ lines }: { lines: LogLine[] }) {
  const style = {
    in: "text-mist-dim",
    out: "text-ok",
    err: "text-bad",
    note: "text-mist-faint",
  };
  return (
    <div className="max-h-72 overflow-y-auto rounded-lg border border-ink-700 bg-ink-950 p-3.5">
      {lines.length === 0 ? (
        <p className="font-mono text-[11px] text-mist-faint">Nothing run yet.</p>
      ) : (
        <ul className="space-y-1">
          {lines.map((line, index) => (
            <li key={index} className={`font-mono text-[11px] leading-relaxed ${style[line.kind]}`}>
              <span className="select-none text-mist-faint">
                {line.kind === "in" ? "› " : line.kind === "err" ? "✗ " : line.kind === "out" ? "✓ " : "  "}
              </span>
              {line.text}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function CryptoLabPage() {
  const { engine, serverEngine, metrics, keyState } = useApp();
  const navigate = useNavigate();

  const [values, setValues] = useState("120, 85, 40, 210");
  const [ciphertext, setCiphertext] = useState<string | null>(null);
  const [lines, setLines] = useState<LogLine[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [sizeComparison, setSizeComparison] = useState<
    { withRotation: number; withoutRotation: number; rotationMs: number } | null
  >(null);
  const [precision, setPrecision] = useState<{ depth: number; error: number }[] | null>(null);

  function log(kind: LogLine["kind"], text: string) {
    setLines((previous) => [...previous, { kind, text }]);
  }

  if (keyState !== "ready" || !engine || !serverEngine || !metrics) {
    return (
      <EmptyState title="Unlock a key to use the lab" action={<Button onClick={() => navigate("/keys")}>Go to keys</Button>}>
        Every demonstration here runs against a real keypair.
      </EmptyState>
    );
  }

  const parsedValues = values
    .split(",")
    .map((v) => Number(v.trim()))
    .filter((v) => Number.isFinite(v));

  function doEncrypt() {
    try {
      const started = performance.now();
      const result = engine!.encrypt(parsedValues);
      const elapsed = performance.now() - started;
      setCiphertext(result);
      log("in", `encrypt([${parsedValues.join(", ")}])`);
      log("out", `${bytes(engine!.ciphertextBytes(result))} of ciphertext in ${ms(elapsed)}`);
    } catch (cause) {
      log("err", cause instanceof Error ? cause.message : String(cause));
    }
  }

  function doServerDecrypt() {
    log("in", "serverEngine.decrypt(ciphertext)");
    try {
      serverEngine!.decrypt(ciphertext!);
      log("err", "the server decrypted it — this should be impossible");
    } catch (cause) {
      log("out", `refused: ${cause instanceof Error ? cause.message : String(cause)}`);
    }
  }

  function doClientDecrypt() {
    log("in", "clientEngine.decrypt(ciphertext)");
    try {
      const out = engine!.decrypt(ciphertext!, parsedValues.length);
      log("out", `[${out.map((v) => num(v, 4)).join(", ")}]`);
      const worst = Math.max(...out.map((v, i) => Math.abs(v - (parsedValues[i] ?? 0))));
      log("note", `worst absolute error ${sci(worst)}`);
    } catch (cause) {
      log("err", cause instanceof Error ? cause.message : String(cause));
    }
  }

  function doHomomorphic() {
    log("in", "serverEngine.dotPlain(ciphertext, [1, 1, 1, …])  // sum of holdings");
    try {
      const started = performance.now();
      const ones = new Array(parsedValues.length).fill(1);
      const encrypted = serverEngine!.dotPlain(ciphertext!, ones);
      const elapsed = performance.now() - started;
      const decrypted = engine!.decrypt(encrypted, 1)[0] ?? 0;
      const truth = parsedValues.reduce((sum, v) => sum + v, 0);
      log("out", `server computed a result in ${ms(elapsed)} without decrypting anything`);
      log("out", `client decrypted: ${num(decrypted, 6)}  (plaintext sum: ${truth})`);
      log("note", `relative error ${sci(Math.abs(decrypted - truth) / Math.abs(truth || 1))}`);
    } catch (cause) {
      log("err", cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function doWrongKey() {
    setBusy("wrongkey");
    log("in", "generating a second, unrelated keypair…");
    try {
      const other = await CkksEngine.createClient(DEFAULT_PARAMS, { rotationKeys: false });
      log("note", `second key id ${other.keyId}`);
      log("in", "otherEngine.decrypt(ciphertext from the first key)");
      try {
        const out = other.decrypt(ciphertext!, parsedValues.length);
        log("err", `decrypted to [${out.map((v) => sci(v)).join(", ")}] — no error was raised`);
      } catch (cause) {
        log("out", `refused: ${cause instanceof Error ? cause.message : String(cause)}`);
        log(
          "note",
          "without the key-id envelope SEAL returns floats of order 1e31 here rather than raising",
        );
      }
    } finally {
      setBusy(null);
    }
  }

  async function doRotationKeyComparison() {
    setBusy("rotation");
    log("in", "generating one keypair with rotation keys and one without…");
    try {
      const withRotationStarted = performance.now();
      const withRotation = await CkksEngine.createClient(DEFAULT_PARAMS, { rotationKeys: true });
      const rotationMs = performance.now() - withRotationStarted;
      const withoutRotation = await CkksEngine.createClient(DEFAULT_PARAMS, { rotationKeys: false });

      const a = withRotation.metrics().publicBundleBytes;
      const b = withoutRotation.metrics().publicBundleBytes;
      setSizeComparison({ withRotation: a, withoutRotation: b, rotationMs });
      log("out", `with rotation keys: ${bytes(a)}`);
      log("out", `without: ${bytes(b)}  →  ${num(a / b, 1)}× smaller`);

      log("in", "attempting a reduction on the key without rotation keys…");
      try {
        withoutRotation.dotPlain(withoutRotation.encrypt(parsedValues), new Array(parsedValues.length).fill(1));
        log("err", "the reduction succeeded — unexpected");
      } catch (cause) {
        log("out", `refused: ${cause instanceof Error ? cause.message : String(cause)}`);
      }
    } finally {
      setBusy(null);
    }
  }

  function doPrecision() {
    log("in", "measuring approximation error against multiplicative depth…");
    try {
      const probe = [1.1, 1.2, 1.3];
      const fresh = engine!.encrypt(probe);
      const rows: { depth: number; error: number }[] = [];

      const decoded0 = engine!.decrypt(fresh, 3);
      rows.push({ depth: 0, error: Math.max(...decoded0.map((v, i) => Math.abs(v - probe[i]!) / probe[i]!)) });

      const doubled = serverEngine!.multiplyScalar(fresh, 2);
      const decoded1 = engine!.decrypt(doubled, 3);
      rows.push({
        depth: 1,
        error: Math.max(...decoded1.map((v, i) => Math.abs(v - probe[i]! * 2) / (probe[i]! * 2))),
      });

      const reduced = serverEngine!.dotPlain(fresh, [1, 1, 1]);
      const truth = probe.reduce((sum, v) => sum + v, 0);
      const reducedValue = engine!.decrypt(reduced, 1)[0] ?? 0;
      rows.push({ depth: 2, error: Math.abs(reducedValue - truth) / truth });

      setPrecision(rows);
      rows.forEach((row) =>
        log("out", `depth ${row.depth}${row.depth === 2 ? " (with reduction)" : ""}: relative error ${sci(row.error)}`),
      );
      log("note", "error grows with depth; a rotate-and-add reduction sums noise from every slot");
    } catch (cause) {
      log("err", cause instanceof Error ? cause.message : String(cause));
    }
  }

  return (
    <div className="space-y-6 animate-riseIn">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Crypto lab</h1>
        <p className="mt-1 text-sm text-mist-dim">
          Every claim this project makes, run live. Open the console below and press the buttons.
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Scheme" value="CKKS" tone="cipher" sub="Microsoft SEAL via WebAssembly" />
        <Stat label="Ring dimension" value={`N = ${metrics.polyModulusDegree.toLocaleString()}`} sub={`${metrics.slotCount.toLocaleString()} slots`} />
        <Stat label="Security" value="128-bit" tone="ok" sub={`${metrics.totalCoeffModulusBits}/${metrics.securityBudgetBits} modulus bits`} />
        <Stat label="Hard problem" value="Ring-LWE" tone="umbra" sub="Shor's algorithm does not apply" />
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[1fr_1fr]">
        <div className="space-y-6">
          <Panel title="1 · Encrypt something" subtitle="Any numbers you like">
            <input
              className="field font-mono"
              value={values}
              onChange={(e) => setValues(e.target.value)}
              placeholder="120, 85, 40, 210"
            />
            <div className="mt-3 flex flex-wrap gap-2">
              <Button onClick={doEncrypt} disabled={parsedValues.length === 0}>
                Encrypt
              </Button>
              <Button variant="ghost" onClick={doClientDecrypt} disabled={!ciphertext}>
                Decrypt (client)
              </Button>
            </div>
            {ciphertext && (
              <div className="mt-4">
                <CiphertextBlock
                  ciphertext={ciphertext}
                  bytes={engine.ciphertextBytes(ciphertext)}
                  chars={220}
                />
              </div>
            )}
          </Panel>

          <Panel
            title="2 · Ask the server to decrypt it"
            subtitle="The whole project in one button"
            actions={<Badge tone="umbra"><Dot tone="umbra" /> the claim</Badge>}
          >
            <p className="text-sm leading-relaxed text-mist-dim">
              The server-side engine is built from the public bundle. It holds evaluation keys, so it can
              compute. It has no decryptor object at all — not a disabled one.
            </p>
            <Button variant="ghost" className="mt-4" onClick={doServerDecrypt} disabled={!ciphertext}>
              Attempt server decryption
            </Button>
          </Panel>

          <Panel title="3 · Compute over it anyway" subtitle="Sum the encrypted values without opening them">
            <p className="text-sm leading-relaxed text-mist-dim">
              One plaintext multiplication and a rotate-and-add reduction, performed by the engine that
              cannot decrypt. The result comes back encrypted.
            </p>
            <Button variant="ghost" className="mt-4" onClick={doHomomorphic} disabled={!ciphertext}>
              Run homomorphic sum
            </Button>
          </Panel>
          <Panel title="4 · Try the wrong key" subtitle="A failure mode SEAL does not catch on its own">
            <p className="text-sm leading-relaxed text-mist-dim">
              Decrypting under a different key of the same parameters does not error in SEAL — it returns
              plausible-looking floats. A user restoring the wrong backup would see numbers. The key-id
              envelope turns that into an exception.
            </p>
            <Button
              variant="ghost"
              className="mt-4"
              loading={busy === "wrongkey"}
              onClick={doWrongKey}
              disabled={!ciphertext}
            >
              Generate a second key and try it
            </Button>
          </Panel>

          <Panel title="5 · What rotation keys cost" subtitle="Measured, not quoted">
            <p className="text-sm leading-relaxed text-mist-dim">
              Every reduction is rotate-and-add, so rotation keys are mandatory for server-side
              computation — and they dominate the key material.
            </p>
            <Button variant="ghost" className="mt-4" loading={busy === "rotation"} onClick={doRotationKeyComparison}>
              Generate both and compare
            </Button>
            {sizeComparison && (
              <div className="mt-5 space-y-4">
                <SizeCompare
                  rows={[
                    { label: "Public bundle with rotation keys", bytes: sizeComparison.withRotation, tone: "cipher" },
                    { label: "Public bundle without", bytes: sizeComparison.withoutRotation, tone: "neutral" },
                  ]}
                />
                <KeyValue
                  rows={[
                    ["Ratio", `${num(sizeComparison.withRotation / sizeComparison.withoutRotation, 1)}×`],
                    ["Generation time", ms(sizeComparison.rotationMs)],
                    ["At N = 16384", "≈ 180 MB — the original spec's default"],
                  ]}
                />
              </div>
            )}
          </Panel>

          <Panel title="6 · Approximation error by depth" subtitle="CKKS trades exactness for computability">
            <Button variant="ghost" onClick={doPrecision} className="mb-4">
              Measure
            </Button>
            {precision && (
              <KeyValue
                rows={precision.map((row) => [
                  row.depth === 0 ? "Fresh ciphertext" : row.depth === 1 ? "After one multiplication" : "After a reduction",
                  sci(row.error),
                ])}
              />
            )}
            <Alert tone="neutral" title="Why this matters for a portfolio">
              A value accurate to parts per million is fine for money. A share count is not — round it on
              the client after decrypting rather than treating a CKKS output as an integer.
            </Alert>
          </Panel>
        </div>

        <div className="space-y-6 lg:sticky lg:top-20">
          <Panel title="Console" subtitle="Live output" actions={<Button variant="quiet" onClick={() => setLines([])}>Clear</Button>}>
            <Console lines={lines} />
          </Panel>

        </div>
      </div>

      <Panel title="Where the post-quantum claim comes from">
        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <h3 className="text-sm font-medium text-mist">The argument</h3>
            <p className="mt-2 text-sm leading-relaxed text-mist-dim">
              CKKS is a Ring Learning With Errors construction. Shor's algorithm solves the hidden
              subgroup problem over abelian groups, which is why it breaks RSA and elliptic curves — it
              does not apply to lattice problems. Grover's gives a square-root speedup on unstructured
              search, which affects symmetric key sizes, not lattice reduction asymptotics.
            </p>
            <p className="mt-3 text-sm leading-relaxed text-mist-dim">
              This is the same reasoning behind NIST's ML-KEM and ML-DSA, which rest on Module-LWE — a
              close relative. The project is not claiming a novel assumption.
            </p>
          </div>
          <div>
            <h3 className="text-sm font-medium text-mist">The honest caveat</h3>
            <p className="mt-2 text-sm leading-relaxed text-mist-dim">
              The published parameter tables target <em>classical</em> security levels. There is no
              equally settled table for quantum levels, because the field has not converged on how to
              cost quantum lattice sieving under realistic memory models. Reading the 128-bit classical
              row as somewhat less than 128 bits of quantum security is the conservative position.
            </p>
            <p className="mt-3 text-sm leading-relaxed text-mist-dim">
              The BB84 simulation in the backend is a demonstration of the protocol — it detects an
              intercept-resend attacker at a measured QBER around 0.22 against the theoretical 0.25 — and
              it is deliberately never the source of a session key.
            </p>
          </div>
        </div>
      </Panel>
    </div>
  );
}
