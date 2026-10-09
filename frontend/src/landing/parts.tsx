import type { ReactNode } from "react";

import { Reveal } from "./effects";

export function SectionHeader({
  eyebrow,
  title,
  intro,
  titleId,
}: {
  eyebrow: string;
  title: string;
  intro?: ReactNode;
  titleId: string;
}) {
  return (
    <Reveal className="mx-auto mb-16 max-w-3xl text-center">
      <p className="lp-eyebrow">{eyebrow}</p>
      <h2
        id={titleId}
        className="mt-4 text-[28px] font-bold leading-[1.2] tracking-[-0.02em] sm:text-4xl lg:text-5xl"
      >
        <span className="lp-gradient-text inline-block pb-[0.08em]">{title}</span>
      </h2>
      {intro && (
        <p className="mx-auto mt-5 max-w-2xl text-base leading-[1.6] text-brand-gray sm:text-lg">{intro}</p>
      )}
    </Reveal>
  );
}

type ChipTone = "cipher" | "umbra" | "ok" | "warn" | "neutral";

const CHIP: Record<ChipTone, string> = {
  cipher: "border-brand-cipher/40 bg-brand-cipher/10 text-sky-300",
  umbra: "border-brand-umbra/50 bg-brand-umbra/15 text-brand-umbra-light",
  ok: "border-brand-ok/40 bg-brand-ok/10 text-emerald-300",
  warn: "border-brand-warn/40 bg-brand-warn/10 text-amber-300",
  neutral: "border-white/10 bg-white/[0.04] text-brand-cloud",
};

export function Chip({ tone = "neutral", children }: { tone?: ChipTone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1 text-xs font-semibold ${CHIP[tone]}`}
    >
      {children}
    </span>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block animate-spin rounded-full border-2 border-current border-t-transparent ${className}`}
    />
  );
}
