import type { ReactNode } from "react";

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className = "",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <header className="panel-hd">
          <div className="min-w-0">
            {title && <h2 className="truncate text-sm font-semibold text-mist">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-mist-faint">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

type ButtonVariant = "primary" | "ghost" | "danger" | "quiet";

const BUTTON_STYLES: Record<ButtonVariant, string> = {
  primary:
    "bg-umbra text-white hover:bg-umbra-bright disabled:bg-ink-600 disabled:text-mist-faint shadow-[0_1px_0_rgba(255,255,255,0.14)_inset]",
  ghost: "border border-ink-600 text-mist hover:border-umbra/60 hover:text-white disabled:text-mist-faint",
  danger: "border border-bad/40 text-bad hover:bg-bad/10 disabled:opacity-50",
  quiet: "text-mist-dim hover:text-mist",
};

export function Button({
  variant = "primary",
  loading = false,
  children,
  className = "",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; loading?: boolean }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium
        transition-colors disabled:cursor-not-allowed ${BUTTON_STYLES[variant]} ${className}`}
    >
      {loading && <Spinner />}
      {children}
    </button>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg className={`h-4 w-4 animate-spin ${className}`} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
      <path d="M14.5 8A6.5 6.5 0 0 0 8 1.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function Field({
  label,
  hint,
  error,
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string; error?: string | null }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <input {...rest} className={`field mt-1.5 ${error ? "border-bad/70" : ""}`} />
      {error ? (
        <span className="mt-1.5 block text-xs text-bad">{error}</span>
      ) : hint ? (
        <span className="mt-1.5 block text-xs text-mist-faint">{hint}</span>
      ) : null}
    </label>
  );
}

type Tone = "neutral" | "cipher" | "ok" | "warn" | "bad" | "umbra";

const BADGE_STYLES: Record<Tone, string> = {
  neutral: "border-ink-600 text-mist-dim",
  cipher: "border-cipher/40 text-cipher bg-cipher/5",
  ok: "border-ok/40 text-ok bg-ok/5",
  warn: "border-warn/40 text-warn bg-warn/5",
  bad: "border-bad/40 text-bad bg-bad/5",
  umbra: "border-umbra/45 text-umbra-bright bg-umbra/10",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px]
        font-medium tracking-wide ${BADGE_STYLES[tone]}`}
    >
      {children}
    </span>
  );
}

export function Dot({ tone = "neutral", pulse = false }: { tone?: Tone; pulse?: boolean }) {
  const color = {
    neutral: "bg-mist-faint",
    cipher: "bg-cipher",
    ok: "bg-ok",
    warn: "bg-warn",
    bad: "bg-bad",
    umbra: "bg-umbra",
  }[tone];
  return <span className={`h-1.5 w-1.5 rounded-full ${color} ${pulse ? "animate-pulseSoft" : ""}`} />;
}

/**
 * A stat tile. The number *is* the chart -- no plot, so no hover layer.
 * Values wear text tokens; any colour lives on the accompanying badge.
 */
export function Stat({
  label,
  value,
  sub,
  tone = "neutral",
  mono = true,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
  mono?: boolean;
}) {
  const accent = {
    neutral: "text-mist",
    cipher: "text-cipher",
    ok: "text-ok",
    warn: "text-warn",
    bad: "text-bad",
    umbra: "text-umbra-bright",
  }[tone];
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-900/60 px-4 py-3.5">
      <div className="label">{label}</div>
      <div className={`mt-1.5 text-xl ${mono ? "font-mono" : "font-semibold"} ${accent}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-mist-faint">{sub}</div>}
    </div>
  );
}

export function Alert({
  tone = "warn",
  title,
  children,
}: {
  tone?: Tone;
  title?: ReactNode;
  children: ReactNode;
}) {
  const styles: Record<Tone, string> = {
    neutral: "border-ink-600 bg-ink-900/60",
    cipher: "border-cipher/30 bg-cipher/[0.06]",
    ok: "border-ok/30 bg-ok/[0.06]",
    warn: "border-warn/30 bg-warn/[0.06]",
    bad: "border-bad/35 bg-bad/[0.07]",
    umbra: "border-umbra/35 bg-umbra/[0.07]",
  };
  return (
    <div className={`rounded-lg border px-4 py-3 text-sm ${styles[tone]}`} role="status">
      {title && <div className="mb-1 font-medium text-mist">{title}</div>}
      <div className="text-mist-dim [&_code]:font-mono [&_code]:text-[12px] [&_code]:text-cipher">
        {children}
      </div>
    </div>
  );
}

export function Progress({ value, tone = "umbra" }: { value: number; tone?: Tone }) {
  const bar = { neutral: "bg-mist-faint", cipher: "bg-cipher", ok: "bg-ok", warn: "bg-warn", bad: "bg-bad", umbra: "bg-umbra" }[tone];
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-700">
      <div
        className={`h-full rounded-full ${bar} transition-[width] duration-500 ease-out`}
        style={{ width: `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%` }}
      />
    </div>
  );
}

export function KeyValue({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="divide-y divide-ink-700/70">
      {rows.map(([key, value], index) => (
        <div key={index} className="flex items-baseline justify-between gap-4 py-2 first:pt-0 last:pb-0">
          <dt className="text-xs text-mist-faint">{key}</dt>
          <dd className="text-right font-mono text-[13px] text-mist">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Ciphertext display. Always this treatment, so it is never mistaken for data. */
export function CiphertextBlock({
  ciphertext,
  bytes,
  label = "ciphertext",
  chars = 320,
}: {
  ciphertext: string;
  bytes?: number;
  label?: string;
  chars?: number;
}) {
  return (
    <div className="rounded-lg border border-cipher/25 bg-cipher/[0.04] p-3.5">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="label text-cipher/80">{label}</span>
        {bytes !== undefined && (
          <span className="font-mono text-[11px] text-mist-faint">{(bytes / 1024).toFixed(0)} kB</span>
        )}
      </div>
      <p className="cipher-text">
        {ciphertext.slice(0, chars)}
        {ciphertext.length > chars && <span className="text-mist-faint">… +{ciphertext.length - chars} chars</span>}
      </p>
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-ink-600 px-6 py-12 text-center">
      <h3 className="text-sm font-medium text-mist">{title}</h3>
      {children && <p className="mt-1.5 max-w-md text-sm text-mist-faint">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
