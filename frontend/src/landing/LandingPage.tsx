/**
 * The public website at `/`.
 *
 * Sections, in order: navigation, hero, features, how it works, live demo
 * (with metrics), security, roadmap, call to action, footer. The app itself
 * lives behind "Launch App" and loads as a separate chunk.
 */

import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { apiOrigin } from "../lib/backend";
import { DecodeText, LatticeField, Reveal } from "./effects";
import { useBackendLink, useReducedMotion, useScrolled, useScrollSpy, type BackendLink } from "./hooks";
import { ArrowDown, ArrowRight, CrossIcon, EclipseMark, ExternalIcon, GitHubIcon, MenuIcon } from "./icons";
import { SectionHeader } from "./parts";
import { Features, HowItWorks, Roadmap, Security } from "./Sections";
import "./landing.css";

const REPO_URL =
  (import.meta.env.VITE_REPO_URL as string | undefined)?.replace(/\/$/, "") ||
  "https://github.com/aag-369/Penumbra.AI";
const DOC = (path: string) => `${REPO_URL}/blob/main/${path}`;

// The demo, and the crypto it pulls in, is fetched when the visitor nears it.
const LiveDemo = lazy(() => import("./LiveDemo"));

const NAV_LINKS = [
  { id: "features", label: "Features" },
  { id: "how-it-works", label: "How It Works" },
  { id: "demo", label: "Demo" },
  { id: "security", label: "Security" },
];

// -- brand --------------------------------------------------------------------------

function Brand() {
  return (
    <a href="#top" className="flex items-center gap-2 rounded-md" aria-label="PENUMBRA.AI — back to top">
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[linear-gradient(135deg,#0ea5e9,#7c3aed)] shadow-[0_0_20px_-4px_rgba(14,165,233,0.6)]">
        <span className="flex h-[26px] w-[26px] items-center justify-center rounded-[6px] bg-brand-ink">
          <EclipseMark size={18} />
        </span>
      </span>
      <span className="lp-gradient-text text-lg font-bold tracking-tight">PENUMBRA.AI</span>
    </a>
  );
}

// -- navigation -----------------------------------------------------------------------

function Nav() {
  const scrolled = useScrolled();
  const active = useScrollSpy(NAV_LINKS.map((l) => l.id));
  const [open, setOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const firstLinkRef = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    firstLinkRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
      toggleRef.current?.focus();
    };
  }, [open]);

  useEffect(() => {
    const close = () => {
      if (window.innerWidth >= 1024) setOpen(false);
    };
    window.addEventListener("resize", close);
    return () => window.removeEventListener("resize", close);
  }, []);

  const solid = scrolled || open;

  return (
    <>
      <header
        className={`fixed inset-x-0 top-0 z-50 border-b transition-[background-color,border-color,backdrop-filter] duration-300 ${
          solid
            ? "border-brand-cipher/10 bg-brand-ink/80 backdrop-blur-[10px]"
            : "border-transparent bg-transparent"
        }`}
      >
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5 sm:px-8 lg:px-12">
          <Brand />

          <nav aria-label="Primary" className="hidden items-center gap-6 lg:flex">
            {NAV_LINKS.map((link) => (
              <a
                key={link.id}
                href={`#${link.id}`}
                aria-current={active === link.id ? "true" : undefined}
                className={`relative rounded-md py-1 text-[15px] font-medium transition-colors duration-300 hover:text-brand-cipher ${
                  active === link.id ? "text-brand-cipher" : "text-brand-cloud"
                }`}
              >
                {link.label}
                <span
                  aria-hidden="true"
                  className={`absolute -bottom-1 left-0 h-0.5 rounded-full bg-brand-cipher transition-all duration-300 ${
                    active === link.id ? "w-full opacity-100" : "w-0 opacity-0"
                  }`}
                />
              </a>
            ))}
            <Link to="/dashboard" className="lp-btn-primary ml-2 px-6 py-2 text-base">
              Launch App
            </Link>
          </nav>

          <button
            ref={toggleRef}
            type="button"
            className="flex h-11 w-11 items-center justify-center rounded-lg text-brand-cipher lg:hidden"
            aria-expanded={open}
            aria-controls="mobile-menu"
            aria-label={open ? "Close menu" : "Open menu"}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <CrossIcon size={24} /> : <MenuIcon size={24} />}
          </button>
        </div>
      </header>
      {open && (
        <div
          id="mobile-menu"
          className="lp-fade-in fixed inset-x-0 bottom-0 top-16 z-40 overflow-y-auto bg-brand-ink/95 px-5 pb-10 pt-6 backdrop-blur-md sm:px-8 lg:hidden"
        >
          <nav aria-label="Mobile" className="flex flex-col">
            {NAV_LINKS.map((link, index) => (
              <a
                key={link.id}
                ref={index === 0 ? firstLinkRef : undefined}
                href={`#${link.id}`}
                onClick={() => setOpen(false)}
                className="flex min-h-[56px] items-center justify-between border-b border-white/[0.06] text-2xl font-semibold text-brand-mist transition-colors hover:text-brand-cipher"
              >
                {link.label}
                <ArrowRight size={20} className="text-brand-cipher" />
              </a>
            ))}
            <Link
              to="/dashboard"
              onClick={() => setOpen(false)}
              className="lp-btn-primary mt-8 min-h-[52px] px-6 py-3 text-lg"
            >
              Launch App
            </Link>
            <a href={REPO_URL} className="lp-btn-secondary mt-3 min-h-[52px] px-6 py-3 text-lg">
              <GitHubIcon /> View on GitHub
            </a>
          </nav>
        </div>
      )}
    </>
  );
}

// -- system status --------------------------------------------------------------------

function SystemStatus({ link }: { link: BackendLink }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const { state, status } = link;

  useEffect(() => {
    if (!open) return;
    const onDown = (event: PointerEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const dot = state === "online" ? "bg-emerald-400" : state === "offline" ? "bg-amber-400" : "bg-brand-gray";
  const label = state === "online" ? "Online" : state === "offline" ? "Demo Mode" : "Checking…";
  const labelTone =
    state === "online" ? "text-emerald-400" : state === "offline" ? "text-amber-400" : "text-brand-gray";
  const origin = status?.apiUrl ? apiOrigin(status.apiUrl) : null;

  return (
    <div ref={wrapRef} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="system-status-detail"
        className="lp-glass flex min-h-[44px] items-center gap-2.5 rounded-lg px-4 py-2.5 text-sm transition-colors hover:border-brand-cipher/40"
      >
        <span className="relative flex h-2 w-2" aria-hidden="true">
          {state !== "checking" && <span className={`lp-ping absolute inset-0 rounded-full ${dot}`} />}
          <span className={`relative h-2 w-2 rounded-full ${dot}`} />
        </span>
        <span className="text-brand-cloud">System Status:</span>
        <span className={`font-bold ${labelTone}`} aria-live="polite">
          {label}
        </span>
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          aria-hidden="true"
          className={`text-brand-gray transition-transform duration-300 ${open ? "rotate-180" : ""}`}
        >
          <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </button>

      {open && (
        <div
          id="system-status-detail"
          role="region"
          aria-label="System status details"
          className="lp-glass lp-fade-in absolute left-1/2 top-full z-30 mt-2 w-[min(88vw,400px)] -translate-x-1/2 p-5 text-left text-sm"
        >
          {state === "online" && status ? (
            <>
              <p className="font-semibold text-brand-mist">PENUMBRA API is reachable</p>
              <dl className="lp-code mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
                <dt className="text-brand-gray">Endpoint</dt>
                <dd className="break-all text-brand-cloud">{origin}/health</dd>
                <dt className="text-brand-gray">Version</dt>
                <dd className="text-brand-cloud">{status.version ?? "—"}</dd>
                <dt className="text-brand-gray">Latency</dt>
                <dd className="text-brand-cloud">
                  {status.latencyMs !== undefined ? `${status.latencyMs.toFixed(0)} ms` : "—"}
                </dd>
              </dl>
              <p className="mt-3 text-xs leading-relaxed text-brand-gray">
                The app will report "API connected". Browser ↔ server ciphertext exchange arrives with Phase
                6; encryption runs in your browser either way.
              </p>
              {origin && (
                <a
                  href={`${origin}/docs`}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-3 inline-flex items-center gap-1.5 font-semibold text-brand-cipher hover:underline"
                >
                  Open the API docs <ExternalIcon size={14} />
                </a>
              )}
            </>
          ) : state === "offline" && status ? (
            <>
              <p className="font-semibold text-brand-mist">Running without a backend</p>
              <p className="mt-2 text-xs leading-relaxed text-brand-gray">
                {status.apiUrl
                  ? `Nothing answered at ${origin}/health within 5 seconds.`
                  : "This deployment has no API configured."}{" "}
                Everything on this page still works: the demo and the app run real CKKS in your browser and
                store data on this device.
              </p>
              <p className="mt-2 text-xs leading-relaxed text-brand-gray">
                To go online locally, run <span className="lp-code text-brand-cloud">start.bat</span>{" "}
                (Windows) or <span className="lp-code text-brand-cloud">bash start.sh</span> from the project
                folder.
              </p>
            </>
          ) : (
            <p className="text-brand-gray">Checking for the API…</p>
          )}
          <p className="mt-3 border-t border-white/[0.06] pt-3 text-[11px] text-brand-gray">
            Checked {status ? new Date(status.checkedAt).toLocaleTimeString() : "—"} · rechecks every 30 s ·{" "}
            <button
              type="button"
              onClick={link.recheck}
              className="font-semibold text-brand-cipher hover:underline"
            >
              check now
            </button>
          </p>
        </div>
      )}
    </div>
  );
}

// -- hero -----------------------------------------------------------------------------

function Hero({ link, reduced }: { link: BackendLink; reduced: boolean }) {
  return (
    <section
      id="top"
      aria-labelledby="hero-title"
      className="relative isolate flex min-h-[100svh] items-center justify-center overflow-hidden px-5 pb-12 pt-20 sm:px-8 lg:px-12"
    >
      <div aria-hidden="true" className="absolute inset-0 -z-10">
        <div className="lp-grid absolute inset-0" />
        <LatticeField />
        <div className="lp-orb -left-24 top-20 bg-brand-cipher" />
        <div className="lp-orb -right-24 bottom-10 bg-brand-umbra" style={{ animationDelay: "-3s, -2s" }} />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_50%_35%,rgba(14,165,233,0.12),transparent_60%)] opacity-20" />
        <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-b from-transparent to-brand-ink" />
      </div>

      <div className="relative mx-auto max-w-4xl text-center">
        <p className="lp-fade-in mx-auto mb-8 inline-flex items-center gap-2 rounded-full border border-brand-cipher/25 bg-brand-cipher/[0.06] px-4 py-1.5 text-xs font-medium text-sky-200 sm:text-sm">
          <span className="h-1.5 w-1.5 rounded-full bg-brand-cipher" aria-hidden="true" />
          <span className="sm:hidden">CKKS · Ring-LWE · in your browser</span>
          <span className="hidden sm:inline">
            CKKS homomorphic encryption · Ring-LWE · runs in your browser
          </span>
        </p>

        <h1
          id="hero-title"
          className="text-[36px] font-bold leading-[1.1] tracking-[-0.03em] text-white sm:text-5xl lg:text-7xl"
        >
          <span className="block">Your Portfolio.</span>
          <span className="block">
            <DecodeText text="Encrypted." reduced={reduced} className="lp-gradient-text" /> Always.
          </span>
        </h1>

        <p className="mx-auto mb-12 mt-6 max-w-2xl text-lg leading-[1.6] text-brand-gray sm:text-xl">
          Homomorphic encryption meets portfolio optimization. Get investment analysis while your holdings
          stay encrypted end to end — the server computes on ciphertext it cannot read.
        </p>

        <div className="flex flex-col items-stretch justify-center gap-4 sm:flex-row sm:items-center">
          <a href="#demo" className="lp-btn-primary lp-btn-lift min-h-[52px] px-8 py-4 text-base">
            Try Live Demo <ArrowRight size={18} />
          </a>
          <a href={REPO_URL} className="lp-btn-secondary min-h-[52px] px-8 py-4 text-base">
            <GitHubIcon /> View on GitHub
          </a>
        </div>

        <div className="mt-10">
          <SystemStatus link={link} />
        </div>
      </div>

      <a
        href="#features"
        className="lp-bob absolute bottom-6 left-1/2 hidden -translate-x-1/2 flex-col items-center gap-1 rounded-md text-xs text-brand-gray/80 transition-colors hover:text-brand-cipher sm:flex"
      >
        Scroll to explore
        <ArrowDown size={16} />
      </a>
    </section>
  );
}

// -- live demo section --------------------------------------------------------------------

function DemoPlaceholder() {
  return (
    <div className="relative mx-auto max-w-4xl" aria-hidden="true">
      <div className="lp-glass lp-border-cipher h-[980px] overflow-hidden p-8 sm:h-[860px]">
        <div className="lp-shimmer h-11 w-full rounded bg-white/[0.03]" />
        <div className="lp-shimmer mt-8 h-6 w-1/2 rounded bg-white/[0.03]" />
        <div className="lp-shimmer mt-6 h-[520px] rounded-lg bg-white/[0.03]" />
      </div>
    </div>
  );
}

function DemoSection() {
  const ref = useRef<HTMLElement>(null);
  const [load, setLoad] = useState(() => typeof window !== "undefined" && window.location.hash === "#demo");

  useEffect(() => {
    if (load) return;
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      setLoad(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setLoad(true);
          observer.disconnect();
        }
      },
      { rootMargin: "1200px 0px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [load]);

  return (
    <section
      ref={ref}
      id="demo"
      aria-labelledby="demo-title"
      className="relative scroll-mt-20 px-5 py-20 sm:px-8 lg:px-12"
    >
      <div
        className="pointer-events-none absolute inset-x-0 top-24 mx-auto h-72 max-w-3xl rounded-full bg-brand-cipher/10 blur-3xl"
        aria-hidden="true"
      />
      <SectionHeader
        titleId="demo-title"
        eyebrow="// 03 · live demo"
        title="Live Encryption Demo"
        intro="Real Microsoft SEAL, compiled to WebAssembly, running in this tab. Nothing below is precomputed — change a share count and every number downstream changes with it."
      />
      {load ? (
        <Suspense fallback={<DemoPlaceholder />}>
          <LiveDemo />
        </Suspense>
      ) : (
        <DemoPlaceholder />
      )}
    </section>
  );
}

// -- call to action ---------------------------------------------------------------------

function CallToAction() {
  return (
    <section aria-labelledby="cta-title" className="relative overflow-hidden px-5 py-20 sm:px-8 lg:px-12">
      <div
        aria-hidden="true"
        className="absolute inset-0 bg-[linear-gradient(90deg,#0e1015,rgba(14,165,233,0.1),#0e1015)]"
      />
      <div
        aria-hidden="true"
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 opacity-[0.07]"
      >
        <EclipseMark size={560} />
      </div>
      <Reveal className="relative mx-auto max-w-4xl text-center">
        <h2
          id="cta-title"
          className="text-[28px] font-bold leading-[1.2] tracking-[-0.02em] text-white sm:text-4xl lg:text-5xl"
        >
          Ready to Encrypt Your Portfolio?
        </h2>
        <p className="mx-auto mb-12 mt-6 max-w-2xl text-lg leading-[1.6] text-brand-cloud sm:text-xl">
          Launch the app and generate your first encryption key in seconds.
        </p>
        <div className="flex flex-col items-stretch justify-center gap-4 sm:flex-row sm:items-center">
          <Link to="/dashboard" className="lp-btn-primary min-h-[52px] px-8 py-4 text-base">
            Launch Full App <ArrowRight size={18} />
          </Link>
          <a href={REPO_URL} className="lp-btn-secondary min-h-[52px] px-8 py-4 text-base">
            <GitHubIcon /> View Source Code
          </a>
        </div>
        <p className="mt-8 text-sm text-brand-gray">
          Your secret key is generated on your device and never transmitted. The server stores ciphertext it
          cannot open.
        </p>
      </Reveal>
    </section>
  );
}

// -- footer -----------------------------------------------------------------------------

function Footer({ link }: { link: BackendLink }) {
  const origin = link.state === "online" && link.status?.apiUrl ? apiOrigin(link.status.apiUrl) : null;
  const columns: {
    heading: string;
    links: { label: string; href: string; internal?: boolean; external?: boolean }[];
  }[] = [
    {
      heading: "Product",
      links: [
        { label: "Features", href: "#features" },
        { label: "Live demo", href: "#demo" },
        { label: "Security", href: "#security" },
        { label: "Launch app", href: "/dashboard", internal: true },
      ],
    },
    {
      heading: "Resources",
      links: [
        { label: "Architecture", href: DOC("docs/ARCHITECTURE.md"), external: true },
        { label: "Spec deviations", href: DOC("docs/SPEC_DEVIATIONS.md"), external: true },
        { label: "Deploy guide", href: DOC("DEPLOY.md"), external: true },
        ...(origin ? [{ label: "API reference", href: `${origin}/docs`, external: true }] : []),
      ],
    },
    {
      heading: "Community",
      links: [
        { label: "GitHub", href: REPO_URL, external: true },
        { label: "Issues", href: `${REPO_URL}/issues`, external: true },
        {
          label: "Project proposal",
          href: DOC("Privacy_Preserving_Quantum_Agentic_Advisor_Proposal.docx"),
          external: true,
        },
      ],
    },
    {
      heading: "Legal",
      links: [
        { label: "Threat model", href: DOC("docs/CRYPTO_ASSUMPTIONS.md"), external: true },
        { label: "License (MIT)", href: DOC("LICENSE"), external: true },
      ],
    },
  ];

  return (
    <footer className="border-t border-brand-cipher/10 bg-brand-ink px-5 py-12 sm:px-8 lg:px-12">
      <div className="mx-auto max-w-7xl">
        <div className="mb-10 flex flex-col justify-between gap-6 sm:flex-row sm:items-center">
          <Brand />
          <p className="max-w-md text-sm text-brand-gray">
            Privacy-preserving investment advisory. The server computes; only you can read the answer.
          </p>
        </div>
        <div className="mb-8 grid grid-cols-2 gap-8 md:grid-cols-4">
          {columns.map((column) => (
            <div key={column.heading}>
              <h2 className="mb-4 text-sm font-bold text-brand-mist">{column.heading}</h2>
              <ul className="space-y-2">
                {column.links.map((item) => (
                  <li key={item.label}>
                    {item.internal ? (
                      <Link to={item.href} className="lp-link rounded-sm text-sm">
                        {item.label}
                      </Link>
                    ) : (
                      <a
                        href={item.href}
                        className="lp-link rounded-sm text-sm"
                        {...(item.external ? { target: "_blank", rel: "noreferrer" } : {})}
                      >
                        {item.label}
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="flex flex-col justify-between gap-3 border-t border-brand-cipher/10 pt-8 text-sm text-brand-gray md:flex-row md:items-center">
          <p>© 2026 PENUMBRA.AI. Cryptography for everyone.</p>
          <p>Ring-LWE Security • 128-bit Level • Post-Quantum Ready</p>
        </div>
      </div>
    </footer>
  );
}

// -- page -------------------------------------------------------------------------------

export default function LandingPage() {
  const reduced = useReducedMotion();
  const link = useBackendLink();

  useEffect(() => {
    document.title = "PENUMBRA.AI - Privacy-Preserving Investment Advisory";
    let canonical = document.querySelector<HTMLLinkElement>('link[rel="canonical"]');
    if (!canonical) {
      canonical = document.createElement("link");
      canonical.rel = "canonical";
      document.head.appendChild(canonical);
    }
    canonical.href = `${window.location.origin}/`;
  }, []);

  return (
    <div className="landing min-h-screen font-sans">
      <a
        href="#main"
        className="sr-only z-[60] rounded-lg bg-brand-cipher px-4 py-2 font-semibold text-brand-ink focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        Skip to content
      </a>
      <Nav />
      <main id="main">
        <Hero link={link} reduced={reduced} />
        <Features />
        <HowItWorks />
        <DemoSection />
        <Security />
        <Roadmap />
        <CallToAction />
      </main>
      <Footer link={link} />
    </div>
  );
}
