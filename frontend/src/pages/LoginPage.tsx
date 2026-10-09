import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Alert, Button, Field } from "../components/ui";
import { useApp } from "../store/AppContext";

export default function LoginPage() {
  const { signIn, signUp, user, backend } = useApp();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"signin" | "signup">("signup");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) navigate("/dashboard", { replace: true });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "signup") await signUp(email, password);
      else await signIn(email, password);
      navigate("/keys", { replace: true });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-5 py-10">
      <div className="w-full max-w-[26rem] animate-riseIn">
        <div className="mb-8 text-center">
          <svg width="44" height="44" viewBox="0 0 32 32" className="mx-auto" aria-hidden="true">
            <circle cx="16" cy="16" r="13" fill="#8b5cf6" />
            <path d="M16 3a13 13 0 000 26z" fill="#08090c" />
            <circle cx="16" cy="16" r="13" fill="none" stroke="#a78bfa" strokeOpacity="0.5" />
          </svg>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight">PENUMBRA</h1>
          <p className="mt-2 text-sm leading-relaxed text-mist-dim">
            Investment advice over a portfolio the server cannot read.
          </p>
        </div>

        <form onSubmit={submit} className="panel space-y-4 p-6">
          <div className="flex rounded-lg border border-ink-600 p-0.5">
            {(["signup", "signin"] as const).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => {
                  setMode(option);
                  setError(null);
                }}
                className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  mode === option ? "bg-umbra/20 text-white" : "text-mist-faint hover:text-mist"
                }`}
              >
                {option === "signup" ? "Create account" : "Sign in"}
              </button>
            ))}
          </div>

          <Field
            label="Email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@university.edu"
          />
          <Field
            label="Password"
            type="password"
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            hint={mode === "signup" ? "At least 12 characters." : undefined}
            placeholder="••••••••••••"
          />

          {error && <Alert tone="bad">{error}</Alert>}

          <Button type="submit" loading={busy} className="w-full">
            {mode === "signup" ? "Create account" : "Sign in"}
          </Button>

          <p className="text-center text-[11px] leading-relaxed text-mist-faint">
            This account governs storage only. Your encryption key is generated separately, in your
            browser, and is never sent anywhere.
          </p>
        </form>

        <div className="mt-5 rounded-lg border border-ink-700 bg-ink-900/50 px-4 py-3">
          <p className="text-[11px] leading-relaxed text-mist-faint">
            {backend?.mode === "live" ? (
              <>
                <span className="text-mist-dim">API connected.</span> Accounts and portfolios still live
                in this browser until the Phase-6 ciphertext interop lands. The CKKS encryption is real
                Microsoft SEAL compiled to WebAssembly either way.
              </>
            ) : (
              <>
                <span className="text-mist-dim">Running standalone.</span> Accounts and portfolios live in
                this browser. The CKKS encryption is real Microsoft SEAL compiled to WebAssembly — only
                storage is local.
              </>
            )}
          </p>
        </div>
      </div>
    </div>
  );
}
