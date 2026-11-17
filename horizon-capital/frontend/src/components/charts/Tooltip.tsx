// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-B51C2BBF93AF
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useCallback, useRef, useState } from "react";

// Shared chart bits: the floating tooltip plus two helpers every SVG chart needs.

export type TooltipRow = { value: string; label?: string; color?: string };

/**
 * Floating readout positioned inside a `relative` chart container. Values lead,
 * labels follow; each row is keyed with a short line in the series colour.
 * It sits beside the anchor on whichever side has more room.
 */
export function Tooltip({
  x,
  y,
  width,
  title,
  rows,
}: {
  x: number;
  y: number;
  width: number;
  title?: string;
  rows: TooltipRow[];
}) {
  const flip = x > width / 2;
  return (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-20 min-w-[112px] max-w-[260px] rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs shadow-lg"
      style={{
        left: x,
        top: Math.max(0, y),
        transform: `translate(${flip ? "calc(-100% - 12px)" : "12px"}, -50%)`,
      }}
    >
      {title && <div className="mb-0.5 text-2xs text-ink-3">{title}</div>}
      {rows.map((row, i) => (
        <div key={i} className="flex items-center gap-2 whitespace-nowrap">
          {row.color && (
            <span className="h-0.5 w-2.5 shrink-0 rounded-full" style={{ background: row.color }} />
          )}
          <span className="nums font-semibold text-ink">{row.value}</span>
          {row.label && <span className="truncate text-ink-2">{row.label}</span>}
        </div>
      ))}
    </div>
  );
}

/**
 * Live content width of an element (ResizeObserver), 0 until measured. A callback
 * ref, so it also attaches when the element mounts after the first render.
 */
export function useWidth<T extends HTMLElement>(): [(el: T | null) => void, number] {
  const [width, setWidth] = useState(0);
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: T | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!el) return;
    setWidth(el.clientWidth);
    observer.current = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.current.observe(el);
  }, []);
  return [ref, width];
}

/** Formatted value with an explicit "+" for positives (formatters only sign negatives). */
export function withSign(value: number, format: (v: number) => string): string {
  const text = format(value);
  return value > 0 && !text.startsWith("+") ? `+${text}` : text;
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token B51C2BBF93AF - verify with scripts/authorship.py verify
