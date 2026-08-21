import { useCallback, useEffect, useState } from "react";

import { Alert, Badge, Button, Dot, KeyValue, Panel, Stat } from "../components/ui";
import { bytes, ms, num, relativeTime, truncateMiddle } from "../lib/format";
import { demoBackend } from "../lib/demoBackend";
import { CkksEngine, DEFAULT_PARAMS } from "../lib/seal";
import type { AuditRecord, EncryptionKeyRecord, EncryptionStats, SystemHealth, User } from "../lib/types";
import { useApp } from "../store/AppContext";

const SEVERITY_TONE = { info: "neutral", warning: "warn", critical: "bad" } as const;

export default function AdminPage() {
  const { user } = useApp();
  const [users, setUsers] = useState<User[]>([]);
  const [keys, setKeys] = useState<EncryptionKeyRecord[]>([]);
  const [audit, setAudit] = useState<AuditRecord[]>([]);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [stats, setStats] = useState<EncryptionStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    // The crypto self-test is a real round-trip on a throwaway keypair, not a
    // version check. If the FHE layer has broken, this is where it surfaces.
    let cryptoOk = false;
    const started = performance.now();
    try {
      const probe = await CkksEngine.createClient(DEFAULT_PARAMS, { rotationKeys: false });
      const roundTrip = probe.decrypt(probe.encrypt([1.5, 2.5, 3.5]), 3);
      cryptoOk = roundTrip.every((value, index) => Math.abs(value - [1.5, 2.5, 3.5][index]!) < 1e-3);
    } catch {
      cryptoOk = false;
    }
    const selftestMs = performance.now() - started;

    setUsers(await demoBackend.listUsers());
    setKeys(await demoBackend.listKeys());
    setAudit(await demoBackend.listAudit());
    setHealth(await demoBackend.health(selftestMs, cryptoOk));
    setStats(await demoBackend.encryptionStats());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function toggleUser(target: User) {
    setError(null);
    try {
      await demoBackend.setUserActive(target.id, !target.is_active);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "action failed");
    }
  }

  return (
    <div className="space-y-6 animate-riseIn">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Administration</h1>
          <p className="mt-1 text-sm text-mist-dim">
            An administrator can see who used the system and how much ciphertext they stored — and not one
            holding.
          </p>
        </div>
        <Button variant="ghost" onClick={() => void refresh()}>
          Refresh
        </Button>
      </header>

      <Alert tone="umbra" title="This is not an access-control decision">
        There is no permission that would let an administrator read a portfolio, because there is no
        secret key on the server to grant access to. That distinction is the point of the project, and it
        is worth stating plainly rather than implying that admin access is merely restricted.
      </Alert>

      {error && <Alert tone="bad">{error}</Alert>}

      {health && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Status"
            value={health.status}
            tone={health.status === "ok" ? "ok" : "warn"}
            sub={health.environment}
            mono={false}
          />
          <Stat label="Uptime" value={`${num(health.uptime_seconds / 60, 1)} min`} sub="since page load" />
          <Stat
            label="Crypto self-test"
            value={health.crypto_ok ? "pass" : "fail"}
            tone={health.crypto_ok ? "ok" : "bad"}
            sub={`real round-trip, ${ms(health.crypto_selftest_ms)}`}
            mono={false}
          />
          <Stat label="Users / portfolios" value={`${health.n_users} / ${health.n_portfolios}`} />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Users" subtitle={`${users.length} registered`}>
          {users.length === 0 ? (
            <p className="text-sm text-mist-faint">No users yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-[11px] uppercase tracking-wider text-mist-faint">
                  <tr className="border-b border-ink-700">
                    <th className="py-2 pr-3 text-left font-medium">Email</th>
                    <th className="py-2 pr-3 text-left font-medium">Role</th>
                    <th className="py-2 pr-3 text-left font-medium">Last seen</th>
                    <th className="py-2 text-right font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-700/70">
                  {users.map((row) => (
                    <tr key={row.id} className="transition-colors hover:bg-ink-800/60">
                      <td className="py-2.5 pr-3 text-[13px] text-mist">{row.email}</td>
                      <td className="py-2.5 pr-3">
                        <Badge tone={row.role === "admin" ? "umbra" : "neutral"}>{row.role}</Badge>
                      </td>
                      <td className="py-2.5 pr-3 text-xs text-mist-faint">
                        {row.last_login_at ? relativeTime(row.last_login_at) : "never"}
                      </td>
                      <td className="py-2.5 text-right">
                        <button
                          onClick={() => void toggleUser(row)}
                          disabled={row.id === user?.id}
                          className={`text-[11px] transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                            row.is_active ? "text-mist-faint hover:text-bad" : "text-ok hover:text-ok"
                          }`}
                        >
                          {row.is_active ? "deactivate" : "reactivate"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel title="Encryption overhead" subtitle="What the privacy guarantee costs in storage">
          {stats && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <Stat label="Registered keys" value={stats.total_keys} sub={`${stats.active_keys} active`} />
                <Stat label="Key material" value={`${num(stats.total_megabytes, 1)} MB`} tone="cipher" />
                <Stat label="Portfolios" value={stats.total_portfolios} />
                <Stat
                  label="Mean ciphertext"
                  value={`${num(stats.mean_ciphertext_kilobytes, 0)} kB`}
                  sub="per portfolio"
                />
              </div>
              <Alert tone="neutral" title="Reading the mean ciphertext size">
                A CKKS ciphertext costs roughly the same whether it packs one value or four thousand. A
                high mean against a low asset count would mean portfolios are being stored one ciphertext
                per ticker — the packing mistake the schema exists to avoid.
              </Alert>
            </>
          )}
        </Panel>
      </div>

      <Panel title="Registered keys" subtitle="Public material only — there is no column for a secret key">
        {keys.length === 0 ? (
          <p className="text-sm text-mist-faint">No keys registered.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[11px] uppercase tracking-wider text-mist-faint">
                <tr className="border-b border-ink-700">
                  <th className="py-2 pr-3 text-left font-medium">Fingerprint</th>
                  <th className="py-2 pr-3 text-right font-medium">Size</th>
                  <th className="py-2 pr-3 text-right font-medium">N</th>
                  <th className="py-2 pr-3 text-right font-medium">Modulus</th>
                  <th className="py-2 pr-3 text-left font-medium">Rotation</th>
                  <th className="py-2 text-left font-medium">Registered</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-700/70">
                {keys.map((key) => (
                  <tr key={key.id} className="transition-colors hover:bg-ink-800/60">
                    <td className="py-2.5 pr-3 font-mono text-[12px] text-cipher">{key.fingerprint}</td>
                    <td className="py-2.5 pr-3 text-right font-mono text-[13px] text-mist">
                      {bytes(key.context_bytes)}
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono text-[13px] text-mist-dim">
                      {key.poly_modulus_degree.toLocaleString()}
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono text-[13px] text-mist-dim">
                      {key.total_coeff_modulus_bits} bits
                    </td>
                    <td className="py-2.5 pr-3">
                      {key.has_galois_keys ? <Badge tone="cipher">yes</Badge> : <Badge>no</Badge>}
                    </td>
                    <td className="py-2.5 text-xs text-mist-faint">{relativeTime(key.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Audit trail" subtitle="Key material and ciphertext bodies are redacted before a row is written">
        {audit.length === 0 ? (
          <p className="text-sm text-mist-faint">Nothing recorded yet.</p>
        ) : (
          <ul className="divide-y divide-ink-700/70">
            {audit.slice(0, 40).map((row) => (
              <li key={row.id} className="flex items-start gap-3 py-2.5">
                <span className="mt-1.5">
                  <Dot tone={SEVERITY_TONE[row.severity]} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-3">
                    <span className="font-mono text-[12px] text-mist">{row.action}</span>
                    <span className="text-[11px] text-mist-faint">{relativeTime(row.created_at)}</span>
                  </div>
                  {Object.keys(row.details).length > 0 && (
                    <div className="mt-0.5 font-mono text-[11px] text-mist-faint">
                      {Object.entries(row.details)
                        .map(([key, value]) => `${key}=${truncateMiddle(String(value), 20, 6)}`)
                        .join("  ")}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="What a full compromise of this server would yield">
        <KeyValue
          rows={[
            ["Ticker symbols", "yes — needed for slot order and market data"],
            ["Number of holdings", "yes"],
            ["Timestamps and ciphertext sizes", "yes"],
            ["Quantities held", "no"],
            ["Cost basis", "no"],
            ["Portfolio value", "no"],
            ["Recommended allocation", "no"],
          ]}
        />
        <p className="mt-4 text-xs leading-relaxed text-mist-faint">
          Ticker visibility is a real residual leak, not an oversight. Padding the asset list to a fixed
          universe and encrypting zero weights for the rest would close it, at the cost of making every
          operation scale with the universe rather than the portfolio. That trade-off belongs in the
          write-up as a decision, not omitted.
        </p>
      </Panel>
    </div>
  );
}
