import { useEffect, useRef, useState, type RefObject } from "react";

import { probeBackend, type BackendStatus } from "../lib/backend";

const REDUCED = "(prefers-reduced-motion: reduce)";

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && window.matchMedia?.(REDUCED).matches === true,
  );
  useEffect(() => {
    const query = window.matchMedia?.(REDUCED);
    if (!query) return;
    const update = () => setReduced(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return reduced;
}

/** True once the page has scrolled past `threshold` pixels. */
export function useScrolled(threshold = 8): boolean {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const update = () => setScrolled(window.scrollY > threshold);
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, [threshold]);
  return scrolled;
}

/** The id of the section currently crossing the middle of the viewport. */
export function useScrollSpy(ids: string[]): string | null {
  const [active, setActive] = useState<string | null>(null);
  const key = ids.join("|");
  useEffect(() => {
    const elements = key
      .split("|")
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => el !== null);
    if (elements.length === 0 || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActive(entry.target.id);
        }
      },
      { rootMargin: "-45% 0px -50% 0px" },
    );
    elements.forEach((el) => observer.observe(el));
    const clearAtTop = () => {
      if (window.scrollY < 200) setActive(null);
    };
    window.addEventListener("scroll", clearAtTop, { passive: true });
    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", clearAtTop);
    };
  }, [key]);
  return active;
}

/** Adds `is-visible` once the element is 10% into the viewport, then stops watching. */
export function useReveal<T extends HTMLElement>(): RefObject<T> {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      el.classList.add("is-visible");
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          el.classList.add("is-visible");
          observer.disconnect();
        }
      },
      { threshold: 0.1 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return ref;
}

/** True while the element is on screen. Used to pause canvas work off-screen. */
export function useOnScreen<T extends HTMLElement>(ref: RefObject<T>): boolean {
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry?.isIntersecting ?? true));
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return visible;
}

export type LinkState = "checking" | "online" | "offline";

export interface BackendLink {
  state: LinkState;
  status: BackendStatus | null;
  recheck: () => void;
}

/**
 * Probe the API's `/health` now and every 30 seconds (5 s timeout each).
 * Never blocks rendering; the page is complete without a backend.
 */
export function useBackendLink(intervalMs = 30_000): BackendLink {
  const [status, setStatus] = useState<BackendStatus | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      const next = await probeBackend();
      if (!cancelled) setStatus(next);
    };
    void run();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void run();
    }, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [intervalMs, tick]);

  const state: LinkState = status === null ? "checking" : status.mode === "live" ? "online" : "offline";
  return { state, status, recheck: () => setTick((t) => t + 1) };
}
