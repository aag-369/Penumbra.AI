/**
 * The explanatory sections: features, how it works, security, roadmap.
 *
 * Every claim here is one the repository can defend. Where the original copy
 * overreached (a server that "runs the optimizer on ciphertext", a server that
 * "never sees your data"), the wording follows docs/CRYPTO_ASSUMPTIONS.md and
 * docs/ARCHITECTURE.md instead.
 */

import type { ComponentType, ReactNode, SVGProps } from "react";

import { Reveal } from "./effects";
import {
  AlertIcon,
  BrowserIcon,
  CheckIcon,
  CloudIcon,
  CrossIcon,
  FrontierIcon,
  KeyIcon,
  LatticeIcon,
  LockIcon,
  PrecisionIcon,
  ServerIcon,
} from "./icons";
import { Chip, SectionHeader } from "./parts";

type IconType = ComponentType<SVGProps<SVGSVGElement> & { size?: number }>;

const SECTION_X = "px-5 sm:px-8 lg:px-12";

/** A dark-slate band with soft edges, so it does not read as a hard stripe. */
function SlateBand({ id, labelledBy, children }: { id: string; labelledBy: string; children: ReactNode }) {
  return (
    <section
      id={id}
      aria-labelledby={labelledBy}
      className={`relative scroll-mt-20 bg-brand-slate py-20 ${SECTION_X}`}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-brand-ink to-transparent"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-brand-ink to-transparent"
      />
      <div aria-hidden="true" className="lp-grid pointer-events-none absolute inset-0 opacity-60" />
      <div className="relative mx-auto max-w-7xl">{children}</div>
    </section>
  );
}

// -- features ---------------------------------------------------------------------

const FEATURES: { icon: IconType; title: string; body: string; meta: string }[] = [
  {
    icon: LockIcon,
    title: "Real Homomorphic Encryption",
    body: "Microsoft SEAL's CKKS scheme, compiled to WebAssembly and running in your browser. The server adds, multiplies and reduces ciphertexts it holds no key to open.",
    meta: "CKKS · SEAL · WebAssembly",
  },
  {
    icon: LatticeIcon,
    title: "Post-Quantum Secure",
    body: "CKKS rests on Ring-LWE — the lattice-problem family behind NIST's ML-KEM and ML-DSA. Shor's algorithm, which breaks RSA and elliptic curves, does not apply to it.",
    meta: "Ring-LWE · 128-bit classical",
  },
  {
    icon: FrontierIcon,
    title: "Intelligent Portfolio Optimization",
    body: "Mean-variance optimization with a risk-tolerance dial. The Markowitz risk term w⊤Σw is evaluated on your encrypted weights, inside CKKS's depth-2 budget.",
    meta: "Markowitz · λ folded into Σ",
  },
  {
    icon: KeyIcon,
    title: "Zero Trust Architecture",
    body: "Keys are generated on your device. The secret key is sealed under your passphrase and never transmitted — the server's engine has no decryptor object at all.",
    meta: "AES-256-GCM key backup · no server keygen",
  },
  {
    icon: PrecisionIcon,
    title: "Measured Precision",
    body: "About 1e-9 relative error on a fresh ciphertext and a few parts per million after a reduction. Measured, not quoted — the demo below reports it live.",
    meta: "Scale 2^40 · 4,096 slots",
  },
  {
    icon: CloudIcon,
    title: "Cloud Native",
    body: "Static frontend on Vercel, FastAPI backend wherever you run it. With no backend at all the app runs standalone in the browser — and the encryption stays real.",
    meta: "Vercel · FastAPI · works offline",
  },
];

export function Features() {
  return (
    <section
      id="features"
      aria-labelledby="features-title"
      className={`relative scroll-mt-20 py-20 ${SECTION_X}`}
    >
      <div className="mx-auto max-w-7xl">
        <SectionHeader
          titleId="features-title"
          eyebrow="// 01 · capabilities"
          title="Why PENUMBRA.AI is Different"
          intro="Most advisors encrypt your data in transit and at rest, then decrypt it to do anything useful. PENUMBRA computes on it while it stays encrypted."
        />
        <ul className="grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((feature, index) => {
            const umbra = index % 2 === 1;
            const Icon = feature.icon;
            return (
              <Reveal key={feature.title} as="li" delay={index * 50}>
                <article
                  className={`lp-glass lp-card flex h-full flex-col p-8 ${umbra ? "lp-border-umbra" : "lp-border-cipher"}`}
                >
                  <span
                    className={`flex h-12 w-12 items-center justify-center rounded-lg border ${
                      umbra
                        ? "border-brand-umbra/40 bg-brand-umbra/15 text-brand-umbra-light"
                        : "border-brand-cipher/35 bg-brand-cipher/10 text-sky-300"
                    }`}
                  >
                    <Icon size={28} />
                  </span>
                  <h3
                    className={`mt-6 text-2xl font-bold leading-[1.3] tracking-tight ${
                      umbra ? "text-brand-umbra-light" : "text-brand-cipher"
                    }`}
                  >
                    {feature.title}
                  </h3>
                  <p className="mt-3 flex-1 text-base leading-[1.6] text-brand-cloud">{feature.body}</p>
                  <p className="lp-code mt-6 border-t border-white/[0.06] pt-4 text-xs text-brand-gray">
                    {feature.meta}
                  </p>
                </article>
              </Reveal>
            );
          })}
        </ul>
      </div>
    </section>
  );
}

// -- how it works -----------------------------------------------------------------

const STEPS: {
  title: string;
  where: { label: string; tone: "cipher" | "umbra" };
  body: string;
  spec: string;
}[] = [
  {
    title: "You Create an Encryption Key",
    where: { label: "In your browser", tone: "cipher" },
    body: "A CKKS keypair is generated on your device. The secret key is sealed under your passphrase and stays there. The public, relinearization and rotation keys go to the server.",
    spec: "N = 8192 | Modulus: 200 bits (≤ 218) | Scale: 2^40 | Rotation keys ≈ 32 MB | Security: 128-bit",
  },
  {
    title: "Upload Your Portfolio (Encrypted)",
    where: { label: "Browser → server", tone: "cipher" },
    body: "A CSV of ticker, quantity and cost basis is parsed and encrypted locally into one packed ciphertext — 4,096 slots, one ciphertext however many holdings. The server receives only that.",
    spec: "Portfolio: pnb1.<key_id>.<base64 CKKS ciphertext>",
  },
  {
    title: "Server Computes Over Encrypted Data",
    where: { label: "On the server", tone: "umbra" },
    body: "Portfolio value, expected return and the Markowitz risk term are evaluated directly on your encrypted weights, using public market data. λ is folded into Σ so the objective fits CKKS's two-level depth budget.",
    spec: "Homomorphic operations: Add, Multiply, Rotate-and-sum, Dot product | Depth 2 of 2",
  },
  {
    title: "You Decrypt Locally",
    where: { label: "In your browser", tone: "cipher" },
    body: "Results come back encrypted under your key and are decrypted in your browser. The server never sees the answer it computed.",
    spec: "Precision: ~1e-9 (fresh) → ~1e-7 (depth 1) → ~1e-5 (with reduction)",
  },
];

export function HowItWorks() {
  return (
    <SlateBand id="how-it-works" labelledBy="how-title">
      <SectionHeader
        titleId="how-title"
        eyebrow="// 02 · the pipeline"
        title="How It Works"
        intro="Four steps, one trust boundary — and your secret key never crosses it."
      />
      <ol className="relative mx-auto max-w-4xl space-y-12">
        <span
          aria-hidden="true"
          className="absolute bottom-10 left-7 top-10 w-px bg-gradient-to-b from-brand-cipher/60 via-brand-umbra/50 to-brand-cipher/40 sm:left-8"
        />
        {STEPS.map((step, index) => (
          <Reveal key={step.title} as="li" delay={index * 50} className="relative flex gap-5 sm:gap-8">
            <span className="relative z-10 flex h-14 w-14 shrink-0 items-center justify-center rounded-lg bg-[linear-gradient(135deg,#0369a1,#7c3aed)] text-2xl font-bold text-white shadow-[0_0_0_4px_#1a202c,0_0_32px_-6px_rgba(14,165,233,0.6)] sm:h-16 sm:w-16">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1 pt-1">
              <Chip tone={step.where.tone}>{step.where.label}</Chip>
              <h3 className="mt-3 text-2xl font-bold leading-[1.25] tracking-tight text-brand-mist sm:text-[28px]">
                {step.title}
              </h3>
              <p className="mt-2 text-base leading-[1.6] text-brand-cloud">{step.body}</p>
              <p className="lp-code mt-4 overflow-x-auto rounded-lg border border-brand-cipher/15 bg-brand-ink p-4 text-brand-cipher">
                {step.spec}
              </p>
            </div>
          </Reveal>
        ))}
      </ol>
    </SlateBand>
  );
}

// -- security -----------------------------------------------------------------------

function SecurityCard({
  title,
  tone,
  children,
}: {
  title: string;
  tone: "cipher" | "umbra";
  children: ReactNode;
}) {
  return (
    <article
      className={`lp-glass-deep h-full p-6 sm:p-8 ${tone === "cipher" ? "lp-border-cipher" : "lp-border-umbra"}`}
    >
      <h3
        className={`mb-6 text-2xl font-bold tracking-tight ${tone === "cipher" ? "text-brand-cipher" : "text-brand-umbra-light"}`}
      >
        {title}
      </h3>
      {children}
    </article>
  );
}

const BOUNDARY: { icon: IconType; title: string; body: string; tone: string }[] = [
  {
    icon: BrowserIcon,
    title: "Your Browser",
    body: "Generates the keypair, holds the secret key, encrypts your holdings and decrypts every result.",
    tone: "border-brand-cipher/35 bg-brand-cipher/10 text-sky-300",
  },
  {
    icon: ServerIcon,
    title: "Your Encrypted Data",
    body: "The API, database and keystore hold ciphertexts and public keys. There is no code path that builds a private engine for your key.",
    tone: "border-brand-umbra/40 bg-brand-umbra/15 text-brand-umbra-light",
  },
  {
    icon: AlertIcon,
    title: "Residual Leakage",
    body: "Ticker symbols, the number of holdings, request timing and ciphertext sizes. Stated plainly rather than hidden.",
    tone: "border-brand-warn/40 bg-brand-warn/10 text-amber-300",
  },
];

export function Security() {
  return (
    <SlateBand id="security" labelledBy="security-title">
      <SectionHeader
        titleId="security-title"
        eyebrow="// 04 · threat model"
        title="Security Architecture"
        intro="Confidentiality by construction, with the leaks written down. Read this section before trusting any privacy product — including this one."
      />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 lg:gap-12">
        <Reveal>
          <SecurityCard title="Trust Boundary" tone="cipher">
            <ul className="space-y-5">
              {BOUNDARY.map((item) => {
                const Icon = item.icon;
                return (
                  <li key={item.title} className="flex gap-4">
                    <span
                      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border ${item.tone}`}
                    >
                      <Icon size={22} />
                    </span>
                    <span>
                      <span className="block font-bold text-brand-mist">{item.title}</span>
                      <span className="mt-1 block text-sm leading-relaxed text-brand-gray">{item.body}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </SecurityCard>
        </Reveal>

        <Reveal delay={50}>
          <SecurityCard title="Ring-LWE Hardness" tone="umbra">
            <p className="text-sm font-bold text-brand-gray">CKKS Parameters</p>
            <dl className="lp-code mt-2 grid grid-cols-[auto_1fr] gap-x-5 gap-y-2 rounded-lg border border-white/[0.06] bg-brand-ink p-4 text-xs sm:text-[13px]">
              {[
                ["N = 8192", "polynomial degree · 4,096 slots"],
                ["q ≈ 2^200", "60 + 40 + 40 + 60 bits, budget 218"],
                ["σ = 3.2", "error standard deviation"],
                ["Δ = 2^40", "encoding scale"],
              ].map(([term, note]) => (
                <div key={term} className="contents">
                  <dt className="whitespace-nowrap text-brand-cloud">{term}</dt>
                  <dd className="text-brand-gray">{note}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-6 text-sm font-bold text-brand-gray">Quantum Security</p>
            <p className="mt-2 text-sm leading-relaxed text-brand-cloud">
              Shor's algorithm breaks RSA and elliptic curves through the abelian hidden-subgroup problem; it
              does not apply to lattices. No known quantum algorithm solves Ring-LWE efficiently — the same
              assumption family NIST standardized in ML-KEM and ML-DSA.
            </p>
            <p className="mt-3 text-xs leading-relaxed text-brand-gray">
              Honest caveat: the parameter tables target classical 128-bit security. Read the quantum margin
              as somewhat lower.
            </p>
          </SecurityCard>
        </Reveal>

        <Reveal delay={100}>
          <SecurityCard title="What Server Sees" tone="cipher">
            <div className="grid gap-6 sm:grid-cols-2">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-amber-300">Sees</p>
                <ul className="lp-code mt-3 space-y-2.5 text-xs text-brand-cloud">
                  {[
                    "Ciphertexts (unreadable)",
                    "Key ID — stops wrong-key decrypts",
                    "Ticker symbols and holding count",
                    "Metadata — API calls, timing, sizes",
                  ].map((item) => (
                    <li key={item} className="flex gap-2">
                      <CheckIcon size={14} className="mt-0.5 shrink-0 text-amber-300" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-emerald-300">Never sees</p>
                <ul className="lp-code mt-3 space-y-2.5 text-xs text-brand-cloud">
                  {[
                    "Share counts, cost basis, portfolio value",
                    "Your secret key",
                    "The decrypted recommendation",
                    "Your passphrase",
                  ].map((item) => (
                    <li key={item} className="flex gap-2">
                      <CrossIcon size={14} className="mt-0.5 shrink-0 text-emerald-300" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </SecurityCard>
        </Reveal>

        <Reveal delay={150}>
          <SecurityCard title="Threat Model" tone="umbra">
            <p className="text-sm font-bold text-emerald-400">Protected</p>
            <p className="mt-1.5 text-sm leading-relaxed text-brand-cloud">
              A fully compromised server, database or keystore; network eavesdroppers; insiders and
              administrators; a subpoena of server data. Each obtains ciphertext.
            </p>
            <p className="mt-5 text-sm font-bold text-amber-400">Not Protected</p>
            <p className="mt-1.5 text-sm leading-relaxed text-brand-cloud">
              A compromised browser (XSS is key theft); a dishonest server returning wrong answers — CKKS
              gives confidentiality, not integrity; traffic analysis; a lost key, which cannot be recovered by
              design.
            </p>
          </SecurityCard>
        </Reveal>
      </div>
    </SlateBand>
  );
}

// -- roadmap ------------------------------------------------------------------------

const PHASES: {
  badge: string;
  title: string;
  body: string;
  status: string;
  statusTone: "ok" | "cipher" | "umbra" | "neutral";
  ring: string;
  text: string;
}[] = [
  {
    badge: "✓",
    title: "Phase 1: Encrypted Core",
    body: "CKKS engine in Python (TenSEAL) and in the browser (node-seal), depth-2 homomorphic operations, keystore, auth, audit trail and REST API. 265 backend tests, 89% coverage.",
    status: "Built",
    statusTone: "ok",
    ring: "border-emerald-500 bg-emerald-500/20 text-emerald-400",
    text: "text-emerald-400",
  },
  {
    badge: "2",
    title: "Phase 2: Agent Orchestration",
    body: "Planning, Risk and Execution-Simulation agents reasoning over encrypted-derived data. Their endpoints answer 501 Not Implemented until it lands.",
    status: "Specified",
    statusTone: "neutral",
    ring: "border-cyan-500 bg-cyan-500/20 text-cyan-400",
    text: "text-cyan-400",
  },
  {
    badge: "3",
    title: "Phase 3: QUBO + Obfuscation",
    body: "Portfolio selection as a QUBO, hidden from the solver by permutation, gauge and rescaling transforms that preserve the optimum.",
    status: "Specified",
    statusTone: "neutral",
    ring: "border-purple-500 bg-purple-500/20 text-purple-400",
    text: "text-purple-400",
  },
  {
    badge: "4",
    title: "Phase 4: Simulated QAOA",
    body: "Dicke-state + XY-mixer QAOA on the obfuscated QUBO, benchmarked honestly against the classical baseline that already ships.",
    status: "Specified",
    statusTone: "neutral",
    ring: "border-blue-500 bg-blue-500/20 text-blue-400",
    text: "text-blue-400",
  },
  {
    badge: "5",
    title: "Phase 5: Durable Job Pipeline",
    body: "Advisory runs move from in-process background tasks to a persistent queue (Celery or arq) with the same contract.",
    status: "Planned",
    statusTone: "neutral",
    ring: "border-indigo-500 bg-indigo-500/20 text-indigo-400",
    text: "text-indigo-400",
  },
  {
    badge: "6",
    title: "Phase 6: Ciphertext Interop",
    body: "node-seal ↔ TenSEAL wire compatibility — a Pyfhel swap or a format shim — so browser ciphertexts reach the live API.",
    status: "Next",
    statusTone: "cipher",
    ring: "border-pink-500 bg-pink-500/20 text-pink-400",
    text: "text-pink-400",
  },
];

export function Roadmap() {
  return (
    <section
      id="roadmap"
      aria-labelledby="roadmap-title"
      className={`relative scroll-mt-20 py-20 ${SECTION_X}`}
    >
      <div className="mx-auto max-w-7xl">
        <SectionHeader
          titleId="roadmap-title"
          eyebrow="// 05 · roadmap"
          title="Development Roadmap"
          intro="What is built, what is specified, and what comes next — the same status the API reports."
        />
        <ol className="relative mx-auto max-w-3xl space-y-8">
          <span
            aria-hidden="true"
            className="absolute bottom-6 left-6 top-6 w-px bg-gradient-to-b from-emerald-500/60 via-brand-umbra/40 to-pink-500/40"
          />
          {PHASES.map((phase, index) => (
            <Reveal key={phase.title} as="li" delay={index * 50} className="relative flex gap-6">
              <span
                className={`relative z-10 flex h-12 w-12 shrink-0 items-center justify-center rounded-full border font-bold shadow-[0_0_0_6px_#0e1015] ${phase.ring}`}
              >
                {phase.badge === "✓" ? <CheckIcon size={20} /> : phase.badge}
              </span>
              <div className="min-w-0 flex-1 pt-1">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                  <h3 className={`text-xl font-bold tracking-tight ${phase.text}`}>{phase.title}</h3>
                  <Chip tone={phase.statusTone}>{phase.status}</Chip>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-brand-gray sm:text-base">{phase.body}</p>
              </div>
            </Reveal>
          ))}
        </ol>
        <Reveal className="mx-auto mt-10 max-w-3xl">
          <p className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-5 py-4 text-sm leading-relaxed text-brand-gray">
            <span className="font-semibold text-brand-cloud">Stretch · BB84 channel.</span> Built as a
            protocol demonstration — it catches an intercept-resend attacker at a measured QBER of about 0.22
            — and deliberately never used as key material. The post-quantum claim rests on Ring-LWE alone.
          </p>
        </Reveal>
      </div>
    </section>
  );
}
