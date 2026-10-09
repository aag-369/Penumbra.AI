/**
 * Two pieces of atmosphere, each drawn from the cryptography rather than
 * pasted on top of it.
 *
 * - {@link LatticeField}: CKKS is secure because finding a short vector in a
 *   high-dimensional lattice is hard. The hero background is a lattice --
 *   points generated from two basis vectors, each nudged by a small "error",
 *   which is what Learning With Errors means.
 * - {@link DecodeText}: a word resolving out of base64, which is what a
 *   ciphertext looks like on the wire.
 *
 * Both stop entirely under `prefers-reduced-motion`.
 */

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { useReveal } from "./hooks";

// -- scroll reveal --------------------------------------------------------------

export function Reveal({
  children,
  delay = 0,
  className = "",
  as: Tag = "div",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
  as?: "div" | "li" | "article";
}) {
  const ref = useReveal<HTMLDivElement>();
  return (
    <Tag
      ref={ref as never}
      className={`lp-reveal ${className}`}
      style={{ "--lp-delay": `${delay}ms` } as CSSProperties}
    >
      {children}
    </Tag>
  );
}

// -- lattice ------------------------------------------------------------------

function gaussian(): number {
  // Box-Muller: the error term in LWE is a narrow discrete Gaussian.
  const u = 1 - Math.random();
  const v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/**
 * Drawn once per resize, then moved by CSS transforms on the compositor, so
 * the hero costs the main thread nothing after the first frame.
 */
export function LatticeField() {
  const baseRef = useRef<HTMLCanvasElement>(null);
  const hotRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const base = baseRef.current;
    const hot = hotRef.current;
    const bctx = base?.getContext("2d");
    const hctx = hot?.getContext("2d");
    if (!base || !hot || !bctx || !hctx) return;

    const spacing = 62;
    const theta = -0.18;
    const b1 = { x: spacing, y: spacing * 0.14 };
    const b2 = { x: spacing * 0.41, y: spacing * 0.9 };

    const draw = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      const width = base.clientWidth;
      const height = base.clientHeight;
      for (const [canvas, ctx] of [
        [base, bctx],
        [hot, hctx],
      ] as const) {
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, width, height);
      }

      const range = Math.ceil(Math.hypot(width, height) / (spacing * 0.8) / 2) + 2;
      const side = range * 2 + 1;
      const xs = new Float32Array(side * side);
      const ys = new Float32Array(side * side);
      const cos = Math.cos(theta);
      const sin = Math.sin(theta);
      let k = 0;
      for (let i = -range; i <= range; i += 1) {
        for (let j = -range; j <= range; j += 1) {
          const lx = i * b1.x + j * b2.x;
          const ly = i * b1.y + j * b2.y;
          xs[k] = width / 2 + lx * cos - ly * sin + gaussian() * 3.2;
          ys[k] = height / 2 + lx * sin + ly * cos + gaussian() * 3.2;
          k += 1;
        }
      }
      const inside = (x: number, y: number, pad: number) =>
        x > -pad && x < width + pad && y > -pad && y < height + pad;

      bctx.beginPath();
      for (let n = 0; n < xs.length; n += 1) {
        const x = xs[n]!;
        const y = ys[n]!;
        if (!inside(x, y, 80)) continue;
        if ((n + 1) % side !== 0) {
          bctx.moveTo(x, y);
          bctx.lineTo(xs[n + 1]!, ys[n + 1]!);
        }
        if (n + side < xs.length) {
          bctx.moveTo(x, y);
          bctx.lineTo(xs[n + side]!, ys[n + side]!);
        }
      }
      bctx.strokeStyle = "rgba(14, 165, 233, 0.07)";
      bctx.lineWidth = 1;
      bctx.stroke();

      bctx.fillStyle = "rgba(148, 163, 184, 0.32)";
      bctx.beginPath();
      for (let n = 0; n < xs.length; n += 1) {
        const x = xs[n]!;
        const y = ys[n]!;
        if (!inside(x, y, 8)) continue;
        const roll = Math.random();
        if (roll < 0.06) {
          // A "hot" point: lit on the twinkle layer instead.
          const rgb = roll < 0.035 ? "14, 165, 233" : "167, 139, 250";
          hctx.fillStyle = `rgba(${rgb}, 0.12)`;
          hctx.beginPath();
          hctx.arc(x, y, 6, 0, Math.PI * 2);
          hctx.fill();
          hctx.fillStyle = `rgba(${rgb}, 0.85)`;
          hctx.beginPath();
          hctx.arc(x, y, 1.8, 0, Math.PI * 2);
          hctx.fill();
          continue;
        }
        bctx.moveTo(x + 1.15, y);
        bctx.arc(x, y, 1.15, 0, Math.PI * 2);
      }
      bctx.fill();
    };

    draw();
    let timer = 0;
    let lastWidth = window.innerWidth;
    const onResize = () => {
      // Mobile browsers fire resize as the URL bar hides; only redraw on real width changes.
      if (window.innerWidth === lastWidth) return;
      lastWidth = window.innerWidth;
      window.clearTimeout(timer);
      timer = window.setTimeout(draw, 150);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  const mask =
    "radial-gradient(ellipse 62% 55% at 50% 44%, rgba(0,0,0,0.12) 0%, rgba(0,0,0,0.55) 55%, #000 85%)";
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 overflow-hidden"
      style={{ WebkitMaskImage: mask, maskImage: mask }}
    >
      <div className="lp-drift absolute -inset-[12%]">
        <canvas ref={baseRef} className="absolute inset-0 h-full w-full" />
        <canvas ref={hotRef} className="lp-twinkle absolute inset-0 h-full w-full" />
      </div>
    </div>
  );
}

// -- decode ---------------------------------------------------------------------

const BASE64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

function scramble(text: string): string {
  return Array.from(text, (c) => (c === " " ? " " : BASE64[Math.floor(Math.random() * BASE64.length)]!)).join(
    "",
  );
}

/**
 * Text that arrives as base64 and resolves, left to right, into itself.
 * Screen readers get the plain text; the animation is `aria-hidden`.
 */
export function DecodeText({
  text,
  reduced,
  className = "",
  startDelay = 350,
}: {
  text: string;
  reduced: boolean;
  className?: string;
  startDelay?: number;
}) {
  const [display, setDisplay] = useState(() => (reduced ? text : scramble(text)));
  const running = useRef(false);
  const [runId, setRunId] = useState(0);

  useEffect(() => {
    if (reduced) {
      setDisplay(text);
      return;
    }
    running.current = true;
    let timer = 0;
    const begin = performance.now() + (runId === 0 ? startDelay : 0);
    const tick = () => {
      const elapsed = performance.now() - begin;
      let done = true;
      const next = Array.from(text, (c, i) => {
        if (elapsed > 180 + i * 95) return c;
        done = false;
        return c === " " ? " " : BASE64[Math.floor(Math.random() * BASE64.length)]!;
      }).join("");
      setDisplay(next);
      if (done) {
        running.current = false;
        window.clearInterval(timer);
      }
    };
    timer = window.setInterval(tick, 45);
    return () => {
      window.clearInterval(timer);
      running.current = false;
    };
  }, [text, reduced, runId, startDelay]);

  return (
    <span
      className="relative inline-block"
      onPointerEnter={() => {
        if (!reduced && !running.current) setRunId((n) => n + 1);
      }}
    >
      <span className="sr-only">{text}</span>
      <span aria-hidden="true" className="invisible">
        {text}
      </span>
      <span aria-hidden="true" className={`absolute left-0 top-0 whitespace-nowrap ${className}`}>
        {display}
      </span>
    </span>
  );
}
