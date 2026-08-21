import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { SizeCompare } from "../components/charts";
import { Alert, Badge, Button, Dot, Field, KeyValue, Panel, Progress, Stat } from "../components/ui";
import { bytes, ms } from "../lib/format";
import { passphraseProblems } from "../lib/vault";
import { useApp } from "../store/AppContext";

export default function KeysPage() {
  const { keyState, metrics, keyRecord, createKey, unlockKey, forgetKey, keyProgress, hasSealedKey } =
    useApp();
  const navigate = useNavigate();

  const [passphrase, setPassphrase] = useState("");
  const [confirm, setConfirm] = useState("");
  const [rotationKeys, setRotationKeys] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const problems = passphrase ? passphraseProblems(passphrase) : [];

  async function generate(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (problems.length) return setError(`Passphrase needs ${problems.join(", ")}.`);
    if (passphrase !== confirm) return setError("The two passphrases do not match.");
    setBusy(true);
    try {
      await createKey(passphrase, rotationKeys);
      setPassphrase("");
      setConfirm("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "key generation failed");
    } finally {
      setBusy(false);
    }
  }

  async function unlock(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await unlockKey(passphrase);
      setPassphrase("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "could not unlock");
    } finally {
      setBusy(false);
    }
  }

  if (keyState === "ready" && metrics) {
    return (
      <div className="space-y-6 animate-riseIn">
        <header>
          <h1 className="text-xl font-semibold tracking-tight">Encryption key</h1>
          <p className="mt-1 text-sm text-mist-dim">
            Generated in this browser. Everything below was measured on this machine.
          </p>
        </header>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Key id" value={metrics.keyId.slice(0, 12)} tone="cipher" sub="minted at generation" />
          <Stat label="Ring dimension" value={`N = ${metrics.polyModulusDegree.toLocaleString()}`} sub={`${metrics.slotCount.toLocaleString()} slots`} />
          <Stat
            label="Security"
            value={`${metrics.totalCoeffModulusBits} / ${metrics.securityBudgetBits} bits`}
            tone="ok"
            sub="modulus used vs 128-bit budget"
          />
          <Stat label="Depth" value={metrics.multiplicativeDepth} sub="ciphertext multiplications" />
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <Panel
            title="Key material"
            subtitle="Sizes measured from the serialised keys"
            actions={
              metrics.hasRotationKeys ? (
                <Badge tone="cipher">
                  <Dot tone="cipher" /> rotation keys
                </Badge>
              ) : (
                <Badge tone="warn">no rotation keys</Badge>
              )
            }
          >
            <SizeCompare
              rows={[
                { label: "Secret key (stays here, sealed)", bytes: metrics.secretKeyBytes, tone: "umbra" },
                { label: "Public key", bytes: metrics.publicKeyBytes, tone: "neutral" },
                { label: "Relinearisation keys", bytes: metrics.relinKeyBytes, tone: "neutral" },
                { label: "Rotation keys", bytes: metrics.rotationKeyBytes, tone: "cipher" },
              ]}
            />
            <div className="mt-5 border-t border-ink-700 pt-4">
              <KeyValue
                rows={[
                  ["Uploaded to the server", bytes(metrics.publicBundleBytes)],
                  ["Kept in this browser", bytes(metrics.secretKeyBytes)],
                  ["Key generation", ms(metrics.keygenMs)],
                  ["Rotation key generation", metrics.rotationKeygenMs ? ms(metrics.rotationKeygenMs) : "—"],
                ]}
              />
            </div>
            <Alert tone="neutral" title="Why rotation keys dominate">
              Every reduction — summing slots, and so every portfolio value — is implemented as
              rotate-and-add, which needs a Galois key per rotation step. They are{" "}
              {metrics.rotationKeyBytes && metrics.publicKeyBytes
                ? `${Math.round(metrics.rotationKeyBytes / metrics.publicKeyBytes)}×`
                : "many times"}{" "}
              the size of the public key. This is why the backend stores public contexts on disk rather
              than in a database column, and why the original specification's <code>N = 2^14</code> would
              have meant roughly 180 MB per user.
            </Alert>
          </Panel>

          <div className="space-y-6">
            <Panel title="What the server received" subtitle="Registered key record">
              {keyRecord ? (
                <KeyValue
                  rows={[
                    ["Fingerprint", keyRecord.fingerprint],
                    ["Bundle size", bytes(keyRecord.context_bytes)],
                    ["Ring dimension", keyRecord.poly_modulus_degree.toLocaleString()],
                    ["Modulus bits", `${keyRecord.total_coeff_modulus_bits}`],
                    ["Security level", `${keyRecord.security_level_bits}-bit`],
                    ["Rotation keys", keyRecord.has_galois_keys ? "yes" : "no"],
                    ["Secret key", "never transmitted"],
                  ]}
                />
              ) : (
                <p className="text-sm text-mist-faint">No key registered.</p>
              )}
            </Panel>

            <Panel title="Danger zone">
              <p className="text-sm leading-relaxed text-mist-dim">
                Deleting the sealed key from this browser is irreversible. Any portfolio encrypted under
                it becomes permanently unreadable — by you, by the server, by anyone. That is what
                &ldquo;the server cannot decrypt&rdquo; means in practice.
              </p>
              <Button
                variant="danger"
                className="mt-4"
                onClick={() => {
                  if (confirm !== "DELETE") {
                    setError('Type DELETE in the field below to confirm.');
                    return;
                  }
                  forgetKey();
                  setConfirm("");
                  setError(null);
                }}
              >
                Delete key from this browser
              </Button>
              <input
                className="field mt-3"
                placeholder="Type DELETE to confirm"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
              {error && <p className="mt-2 text-xs text-bad">{error}</p>}
            </Panel>
          </div>
        </div>

        <div className="flex justify-end">
          <Button onClick={() => navigate("/portfolio")}>Continue to portfolio →</Button>
        </div>
      </div>
    );
  }

  if (keyState === "generating") {
    return (
      <div className="mx-auto max-w-lg animate-riseIn">
        <Panel title="Working">
          <p className="text-sm text-mist-dim">{keyProgress ?? "Please wait…"}</p>
          <div className="mt-4">
            <Progress value={0.6} />
          </div>
          <p className="mt-4 text-xs leading-relaxed text-mist-faint">
            Key generation runs entirely on this machine. Rotation keys are tens of megabytes, so this
            takes a moment on first use.
          </p>
        </Panel>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-lg space-y-6 animate-riseIn">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">
          {hasSealedKey ? "Unlock your key" : "Create your encryption key"}
        </h1>
        <p className="mt-1.5 text-sm leading-relaxed text-mist-dim">
          {hasSealedKey
            ? "Your sealed key is in this browser. The passphrase is not — it is never stored, so it has to be entered again after a reload."
            : "A CKKS keypair is generated here, in your browser. The public half goes to the server; the secret half never leaves this device."}
        </p>
      </header>

      {hasSealedKey ? (
        <form onSubmit={unlock} className="panel space-y-4 p-6">
          <Field
            label="Passphrase"
            type="password"
            autoComplete="current-password"
            required
            value={passphrase}
            onChange={(e) => setPassphrase(e.target.value)}
          />
          {error && <Alert tone="bad">{error}</Alert>}
          <Button type="submit" loading={busy} className="w-full">
            Unlock
          </Button>
          <button
            type="button"
            onClick={forgetKey}
            className="w-full text-center text-[11px] text-mist-faint transition-colors hover:text-bad"
          >
            Forget this key and start over
          </button>
        </form>
      ) : (
        <form onSubmit={generate} className="panel space-y-4 p-6">
          <Field
            label="Passphrase"
            type="password"
            autoComplete="new-password"
            required
            value={passphrase}
            onChange={(e) => setPassphrase(e.target.value)}
            hint="Seals the secret key at rest. At least 12 characters, with a letter and a digit."
            error={passphrase && problems.length ? `Needs ${problems.join(", ")}.` : null}
          />
          <Field
            label="Confirm passphrase"
            type="password"
            autoComplete="new-password"
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />

          <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-ink-600 p-3.5">
            <input
              type="checkbox"
              checked={rotationKeys}
              onChange={(e) => setRotationKeys(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-[#8b5cf6]"
            />
            <span className="text-xs leading-relaxed text-mist-dim">
              <span className="font-medium text-mist">Generate rotation keys</span> — required for the
              server to compute portfolio values under encryption. Adds roughly 33 MB of key material
              and a few hundred milliseconds. Turn this off to see what breaks without them.
            </span>
          </label>

          {error && <Alert tone="bad">{error}</Alert>}

          <Alert tone="warn" title="There is no recovery">
            Lose this passphrase and the portfolio encrypted under it is unreadable permanently. No
            administrator can help, because no administrator has the key.
          </Alert>

          <Button type="submit" loading={busy} className="w-full">
            Generate keypair
          </Button>
        </form>
      )}
    </div>
  );
}
