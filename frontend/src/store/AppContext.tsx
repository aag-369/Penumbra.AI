/**
 * Application state: session, key lifecycle, portfolio, backend status.
 *
 * One context rather than four. The pieces are genuinely coupled -- signing out
 * has to drop key material, and uploading a portfolio needs both the key and the
 * session -- and splitting them would mean either prop-drilling or a web of
 * cross-context effects.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { probeBackend, type BackendStatus } from "../lib/backend";
import { demoBackend, DemoError } from "../lib/demoBackend";
import { CkksEngine, DEFAULT_PARAMS, type KeyMetrics } from "../lib/seal";
import type { EncryptionKeyRecord, PortfolioRecord, User } from "../lib/types";
import { clearSealed, readSealed, seal, storeSealed, unseal, VaultError } from "../lib/vault";

export type KeyState = "none" | "locked" | "generating" | "ready";

interface AppState {
  ready: boolean;
  backend: BackendStatus | null;

  user: User | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;

  keyState: KeyState;
  engine: CkksEngine | null;
  /** The server's view of the same key: evaluation keys, no secret key. */
  serverEngine: CkksEngine | null;
  keyRecord: EncryptionKeyRecord | null;
  metrics: KeyMetrics | null;
  keyProgress: string | null;
  hasSealedKey: boolean;
  createKey: (passphrase: string, rotationKeys: boolean) => Promise<void>;
  unlockKey: (passphrase: string) => Promise<void>;
  forgetKey: () => void;

  portfolio: PortfolioRecord | null;
  holdings: number[] | null;
  setPortfolio: (record: PortfolioRecord, plaintext: number[]) => void;
  refreshPortfolio: () => Promise<void>;
}

const AppContext = createContext<AppState | undefined>(undefined);

export function AppProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [backend, setBackend] = useState<BackendStatus | null>(null);
  const [user, setUser] = useState<User | null>(null);

  const [keyState, setKeyState] = useState<KeyState>("none");
  const [engine, setEngine] = useState<CkksEngine | null>(null);
  const [serverEngine, setServerEngine] = useState<CkksEngine | null>(null);
  const [keyRecord, setKeyRecord] = useState<EncryptionKeyRecord | null>(null);
  const [metrics, setMetrics] = useState<KeyMetrics | null>(null);
  const [keyProgress, setKeyProgress] = useState<string | null>(null);
  const [hasSealedKey, setHasSealedKey] = useState(false);

  const [portfolio, setPortfolioRecord] = useState<PortfolioRecord | null>(null);
  const [holdings, setHoldings] = useState<number[] | null>(null);

  const bootstrapped = useRef(false);

  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    void (async () => {
      setBackend(await probeBackend());
      const restored = demoBackend.restoreSession();
      if (restored) setUser(restored);
      const sealed = readSealed();
      setHasSealedKey(sealed !== null);
      // A sealed key exists but the passphrase is not in memory -- the user has
      // to unlock before anything can be decrypted. Reloading the page always
      // lands here, which is the correct behaviour for a client-held secret.
      if (sealed) setKeyState("locked");
      setReady(true);
    })();
  }, []);

  const loadKeyRecord = useCallback(async () => {
    setKeyRecord(await demoBackend.activeKey());
  }, []);

  const signIn = useCallback(
    async (email: string, password: string) => {
      setUser(await demoBackend.login(email, password));
      await loadKeyRecord();
    },
    [loadKeyRecord],
  );

  const signUp = useCallback(
    async (email: string, password: string) => {
      setUser(await demoBackend.register(email, password));
    },
    [],
  );

  const signOut = useCallback(async () => {
    await demoBackend.logout();
    setUser(null);
    // Drop key material from memory. The sealed copy stays on disk so the user
    // can unlock again; what leaves is the usable key.
    setEngine(null);
    setServerEngine(null);
    setMetrics(null);
    setPortfolioRecord(null);
    setHoldings(null);
    setKeyState(readSealed() ? "locked" : "none");
  }, []);

  const adoptEngine = useCallback(async (client: CkksEngine, registerWithServer: boolean) => {
    // Build the server's view from the public bundle -- the same object the
    // real API would construct. It has no decryptor at all.
    const publicBundle = client.exportPublicBundle();
    const server = await CkksEngine.fromPublicBundle(publicBundle);
    setEngine(client);
    setServerEngine(server);
    setMetrics(client.metrics());
    setKeyState("ready");

    if (registerWithServer) {
      const m = client.metrics();
      setKeyRecord(
        await demoBackend.registerKey({
          keyId: m.keyId,
          polyModulusDegree: m.polyModulusDegree,
          totalCoeffModulusBits: m.totalCoeffModulusBits,
          hasRotationKeys: m.hasRotationKeys,
          bundleBytes: m.publicBundleBytes,
          slotCount: m.slotCount,
          multiplicativeDepth: m.multiplicativeDepth,
          containsSecretKey: false,
        }),
      );
    } else {
      await loadKeyRecord();
    }
  }, [loadKeyRecord]);

  const createKey = useCallback(
    async (passphrase: string, rotationKeys: boolean) => {
      setKeyState("generating");
      try {
        setKeyProgress("Loading the SEAL WebAssembly module…");
        const client = await CkksEngine.createClient(DEFAULT_PARAMS, { rotationKeys });

        setKeyProgress("Sealing the secret key under your passphrase…");
        const blob = await seal(
          {
            keyId: client.keyId,
            secretKey: client.exportSecretKey(),
            polyModulusDegree: DEFAULT_PARAMS.polyModulusDegree,
            coeffModBitSizes: DEFAULT_PARAMS.coeffModBitSizes,
            scaleBits: DEFAULT_PARAMS.scaleBits,
            createdAt: new Date().toISOString(),
          },
          passphrase,
        );
        storeSealed(blob);
        setHasSealedKey(true);

        setKeyProgress("Registering the public half…");
        await adoptEngine(client, true);
        setKeyProgress(null);
      } catch (error) {
        setKeyState(readSealed() ? "locked" : "none");
        setKeyProgress(null);
        throw error;
      }
    },
    [adoptEngine],
  );

  const unlockKey = useCallback(
    async (passphrase: string) => {
      const blob = readSealed();
      if (!blob) throw new VaultError("no sealed key in this browser");
      setKeyState("generating");
      try {
        setKeyProgress("Opening the sealed key…");
        const payload = await unseal(blob, passphrase);

        setKeyProgress("Regenerating evaluation keys from the secret key…");
        const client = await CkksEngine.fromSecretKey(
          payload.secretKey,
          payload.keyId,
          {
            polyModulusDegree: payload.polyModulusDegree,
            coeffModBitSizes: payload.coeffModBitSizes,
            scaleBits: payload.scaleBits,
          },
          { rotationKeys: true },
        );
        await adoptEngine(client, false);
        setKeyProgress(null);
      } catch (error) {
        setKeyState("locked");
        setKeyProgress(null);
        throw error;
      }
    },
    [adoptEngine],
  );

  const forgetKey = useCallback(() => {
    clearSealed();
    setHasSealedKey(false);
    setEngine(null);
    setServerEngine(null);
    setMetrics(null);
    setKeyState("none");
    setPortfolioRecord(null);
    setHoldings(null);
  }, []);

  const setPortfolio = useCallback((record: PortfolioRecord, plaintext: number[]) => {
    setPortfolioRecord(record);
    setHoldings(plaintext);
  }, []);

  const refreshPortfolio = useCallback(async () => {
    const record = await demoBackend.currentPortfolio();
    setPortfolioRecord(record);
    if (record?.holdings_ciphertext && engine) {
      try {
        setHoldings(engine.decrypt(record.holdings_ciphertext, record.n_assets));
      } catch {
        // Wrong key for this ciphertext -- surfaced by the page, not here.
        setHoldings(null);
      }
    } else {
      setHoldings(null);
    }
  }, [engine]);

  useEffect(() => {
    if (keyState === "ready") void refreshPortfolio();
  }, [keyState, refreshPortfolio]);

  const value = useMemo<AppState>(
    () => ({
      ready,
      backend,
      user,
      signIn,
      signUp,
      signOut,
      keyState,
      engine,
      serverEngine,
      keyRecord,
      metrics,
      keyProgress,
      hasSealedKey,
      createKey,
      unlockKey,
      forgetKey,
      portfolio,
      holdings,
      setPortfolio,
      refreshPortfolio,
    }),
    [
      ready, backend, user, signIn, signUp, signOut, keyState, engine, serverEngine, keyRecord,
      metrics, keyProgress, hasSealedKey, createKey, unlockKey, forgetKey, portfolio, holdings,
      setPortfolio, refreshPortfolio,
    ],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppState {
  const context = useContext(AppContext);
  if (!context) throw new Error("useApp must be used inside an AppProvider");
  return context;
}

export { DemoError };
