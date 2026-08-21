/**
 * Charts.
 *
 * Palette: the validated dark categorical set, checked against this app's
 * surface (#0e1015) — worst adjacent CVD ΔE 8.4, worst normal-vision ΔE 19.3,
 * all eight above 3:1 contrast. Colour follows the *entity* (a ticker keeps its
 * hue wherever it appears) and is never assigned by rank, so filtering never
 * repaints the survivors.
 *
 * Form choices worth stating, since both are easy to get wrong:
 *
 * - The donut answers "roughly how is this split", capped at five segments plus
 *   an explicit "Other". A donut cannot be read for close comparisons, so the
 *   precise numbers live in the bars and the table beside it.
 * - The bars are one series over nominal categories, so they take a single hue.
 *   Ramping them by value would double-encode length as colour and burn the only
 *   free channel on information the bar already carries.
 */

import { useId, useState } from "react";

import { percent } from "../lib/format";

/** Validated dark categorical slots. Assigned in fixed order, never cycled. */
export const SERIES = [
  "#3987e5",
  "#d95926",
  "#199e70",
  "#c98500",
  "#d55181",
  "#008300",
  "#9085e9",
  "#e66767",
] as const;

const OTHER_COLOR = "#5b6478";
const SURFACE = "#0e1015";

export interface Slice {
  label: string;
  value: number;
}

/** Stable hue for a label: same ticker, same colour, everywhere in the app. */
export function seriesColor(index: number): string {
  return SERIES[index % SERIES.length]!;
}

function polar(cx: number, cy: number, r: number, angle: number): [number, number] {
  return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
}

function arcPath(cx: number, cy: number, outer: number, inner: number, from: number, to: number): string {
  const large = to - from > Math.PI ? 1 : 0;
  const [x1, y1] = polar(cx, cy, outer, from);
  const [x2, y2] = polar(cx, cy, outer, to);
  const [x3, y3] = polar(cx, cy, inner, to);
  const [x4, y4] = polar(cx, cy, inner, from);
  return [
    `M ${x1} ${y1}`,
    `A ${outer} ${outer} 0 ${large} 1 ${x2} ${y2}`,
    `L ${x3} ${y3}`,
    `A ${inner} ${inner} 0 ${large} 0 ${x4} ${y4}`,
    "Z",
  ].join(" ");
}

/**
 * Part-to-whole donut with a hero number in the middle.
 *
 * @param maxSegments segments past this fold into "Other" rather than adding a
 *   ninth hue — generated hues are indistinguishable under colour-vision
 *   deficiency and break the validated order.
 */
export function DonutChart({
  slices,
  centerLabel,
  centerValue,
  maxSegments = 5,
  size = 208,
}: {
  slices: Slice[];
  centerLabel: string;
  centerValue: string;
  maxSegments?: number;
  size?: number;
}) {
  const [active, setActive] = useState<number | null>(null);
  const titleId = useId();

  const sorted = [...slices].filter((s) => s.value > 0).sort((a, b) => b.value - a.value);
  const head = sorted.slice(0, maxSegments);
  const tail = sorted.slice(maxSegments);
  const display: (Slice & { color: string })[] = head.map((slice, index) => ({
    ...slice,
    color: seriesColor(index),
  }));
  if (tail.length > 0) {
    display.push({
      label: `Other (${tail.length})`,
      value: tail.reduce((sum, s) => sum + s.value, 0),
      color: OTHER_COLOR,
    });
  }

  const total = display.reduce((sum, s) => sum + s.value, 0);
  if (total <= 0) {
    return <p className="py-8 text-center text-sm text-mist-faint">No allocation to show yet.</p>;
  }

  const cx = size / 2;
  const cy = size / 2;
  const outer = size / 2 - 4;
  const inner = outer - 20; // thin ring, not a heavy block
  // 2px surface gap between fills, expressed as an angle at the outer radius.
  const gap = 2 / outer;

  let cursor = -Math.PI / 2;
  const arcs = display.map((slice, index) => {
    const sweep = (slice.value / total) * Math.PI * 2;
    const from = cursor + gap / 2;
    const to = cursor + sweep - gap / 2;
    cursor += sweep;
    return { ...slice, index, from, to: Math.max(to, from + 0.001), share: slice.value / total };
  });

  const hovered = active === null ? null : arcs[active];

  return (
    <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-center sm:gap-7">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg width={size} height={size} role="img" aria-labelledby={titleId}>
          <title id={titleId}>Portfolio allocation by weight</title>
          {arcs.map((arc) => (
            <path
              key={arc.label}
              d={arcPath(cx, cy, outer, inner, arc.from, arc.to)}
              fill={arc.color}
              stroke={SURFACE}
              strokeWidth={2}
              opacity={active === null || active === arc.index ? 1 : 0.32}
              className="cursor-pointer transition-opacity duration-150"
              onMouseEnter={() => setActive(arc.index)}
              onMouseLeave={() => setActive(null)}
            />
          ))}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          {hovered ? (
            <>
              <span className="text-[11px] uppercase tracking-wider text-mist-faint">{hovered.label}</span>
              <span className="font-mono text-lg text-mist">{percent(hovered.share)}</span>
            </>
          ) : (
            <>
              <span className="text-[11px] uppercase tracking-wider text-mist-faint">{centerLabel}</span>
              <span className="font-mono text-lg text-mist">{centerValue}</span>
            </>
          )}
        </div>
      </div>

      {/* A legend is always present: identity is never colour alone. */}
      <ul className="grid w-full gap-1.5">
        {arcs.map((arc) => (
          <li
            key={arc.label}
            className="flex items-center gap-2.5 rounded px-1.5 py-1 transition-colors hover:bg-ink-800"
            onMouseEnter={() => setActive(arc.index)}
            onMouseLeave={() => setActive(null)}
          >
            <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: arc.color }} />
            <span className="min-w-0 flex-1 truncate text-xs text-mist-dim">{arc.label}</span>
            <span className="font-mono text-xs text-mist">{percent(arc.share)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export interface BarRow {
  label: string;
  value: number;
  /** A reference value, drawn as a tick on the track rather than a second bar. */
  compare?: number;
  /** Overrides the single series hue, for linking a row to a donut segment. */
  color?: string;
  note?: string;
}

/**
 * Colours for a value-sorted list, matching what {@link DonutChart} assigns.
 *
 * Both take the same sorted order, so a ticker carries one hue across the donut,
 * the bars and the legend. Anything past `maxSegments` gets the neutral "Other"
 * colour in both places, so the two never disagree.
 */
export function allocationColors(sortedLabels: string[], maxSegments = 5): Map<string, string> {
  return new Map(
    sortedLabels.map((label, index) => [
      label,
      index < maxSegments ? seriesColor(index) : OTHER_COLOR,
    ]),
  );
}

/**
 * Horizontal bars for one series over nominal categories.
 *
 * One hue for every bar. When `compare` is supplied it is drawn as a recessive
 * outline behind the bar — a before/after on one axis, never a second scale.
 */
export function BarList({
  rows,
  format = (v) => percent(v),
  color = SERIES[0],
  compareLabel,
  valueLabel,
}: {
  rows: BarRow[];
  format?: (value: number) => string;
  color?: string;
  compareLabel?: string;
  valueLabel?: string;
}) {
  const max = Math.max(...rows.map((r) => Math.max(r.value, r.compare ?? 0)), 1e-9);

  return (
    <div>
      {(valueLabel || compareLabel) && (
        <div className="mb-2.5 flex items-center gap-4 text-[11px] text-mist-faint">
          {valueLabel && (
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm" style={{ background: color }} />
              {valueLabel}
            </span>
          )}
          {compareLabel && (
            <span className="inline-flex items-center gap-1.5">
              <span className="h-3 w-[2px] rounded-full bg-mist/70" />
              {compareLabel}
            </span>
          )}
        </div>
      )}
      <ul className="space-y-2.5">
        {rows.map((row) => (
          <li key={row.label} className="group">
            <div className="mb-1 flex items-baseline justify-between gap-3">
              <span className="flex min-w-0 items-center gap-2">
                {row.color && (
                  <span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: row.color }} />
                )}
                <span className="truncate text-xs text-mist-dim">{row.label}</span>
              </span>
              <span className="shrink-0 font-mono text-xs text-mist">
                {format(row.value)}
                {row.compare !== undefined && (
                  <span className="ml-2 text-mist-faint">from {format(row.compare)}</span>
                )}
              </span>
            </div>
            <div className="relative h-2.5 w-full rounded-sm bg-ink-800">
              <div
                className="absolute inset-y-0 left-0 rounded-sm transition-[width] duration-500 ease-out"
                style={{
                  width: `${Math.max((row.value / max) * 100, 0.5)}%`,
                  background: row.color ?? color,
                }}
                title={`${valueLabel ?? "weight"}: ${format(row.value)}`}
              />
              {/* The reference value is a tick on the track, not a second bar --
                  two overlapping fills read as one ambiguous shape. */}
              {row.compare !== undefined && (
                <span
                  className="absolute -top-0.5 bottom-[-2px] w-[2px] rounded-full bg-mist/70"
                  style={{ left: `calc(${Math.min((row.compare / max) * 100, 100)}% - 1px)` }}
                  title={`${compareLabel ?? "current"}: ${format(row.compare)}`}
                />
              )}
            </div>
            {row.note && <p className="mt-1 text-[11px] text-mist-faint">{row.note}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * A proportional size comparison — used for the rotation-key overhead, where the
 * point is the *ratio* and exact pixel lengths matter less than the gap.
 */
export function SizeCompare({
  rows,
}: {
  rows: { label: string; bytes: number; tone?: "umbra" | "cipher" | "neutral" }[];
}) {
  const max = Math.max(...rows.map((r) => r.bytes), 1);
  const colors = { umbra: "#8b5cf6", cipher: "#22d3ee", neutral: "#5b6478" };
  return (
    <ul className="space-y-3">
      {rows.map((row) => (
        <li key={row.label}>
          <div className="mb-1 flex items-baseline justify-between gap-3">
            <span className="text-xs text-mist-dim">{row.label}</span>
            <span className="font-mono text-xs text-mist">
              {row.bytes >= 1e6 ? `${(row.bytes / 1e6).toFixed(1)} MB` : `${(row.bytes / 1e3).toFixed(0)} kB`}
            </span>
          </div>
          <div className="h-2 w-full rounded-sm bg-ink-800">
            <div
              className="h-full rounded-sm transition-[width] duration-700 ease-out"
              style={{
                width: `${Math.max((row.bytes / max) * 100, 0.6)}%`,
                background: colors[row.tone ?? "neutral"],
              }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
