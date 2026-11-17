// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-7CF1D7855BC7
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import clsx from "clsx";
import {
  CircleCheck,
  Inbox,
  LoaderCircle,
  Minus,
  OctagonAlert,
  OctagonX,
  TriangleAlert,
  X,
  type LucideIcon,
} from "lucide-react";
import { createElement, isValidElement, type ReactElement, type ReactNode } from "react";

// Small shared primitives. One file on purpose — they are a few lines each and
// splitting them across a components/ tree only adds imports to read through.

export function Card({
  title,
  subtitle,
  action,
  className,
  bodyClassName,
  children,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}) {
  return (
    <section className={clsx("card overflow-hidden", className)}>
      {(title || action) && (
        <header className="flex h-10 items-center justify-between gap-3 border-b border-line px-3">
          <div className="min-w-0">
            {title && <h2 className="truncate text-sm font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="truncate text-xs text-ink-3">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={clsx(bodyClassName ?? "p-3")}>{children}</div>
    </section>
  );
}

// ponytail: mirrors the StatTile layout instead of importing charts/StatTile, so the
// legacy `icon`/`valueClass` props keep working and ui.tsx has no chart dependency.
export function Stat({
  label,
  value,
  hint,
  valueClass,
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  valueClass?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="card min-h-[84px] px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wide text-ink-3">
        {icon}
        {label}
      </div>
      <div className={clsx("mt-1 text-[22px] font-semibold leading-7 text-ink", valueClass)}>
        {value}
      </div>
      {hint !== undefined && <div className="mt-0.5 text-xs text-ink-3">{hint}</div>}
    </div>
  );
}

const BADGE_TONES: Record<string, string> = {
  neutral: "bg-surface-2 text-ink-2 border-line",
  good: "bg-ok/10 text-ink border-ok/30",
  bad: "bg-crit/10 text-ink border-crit/30",
  warn: "bg-warn/15 text-ink border-warn/40",
  accent: "bg-accent/10 text-ink border-accent/30",
};

export function Badge({
  children,
  tone = "neutral",
  icon,
  className,
}: {
  children: ReactNode;
  tone?: keyof typeof BADGE_TONES | string;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded border px-1.5 py-px text-2xs font-medium uppercase tracking-wide",
        BADGE_TONES[tone] ?? BADGE_TONES.neutral,
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

export type StatusChipTone = "ok" | "warning" | "serious" | "critical" | "neutral";

const STATUS_CHIP: Record<StatusChipTone, { cls: string; iconCls: string; icon: LucideIcon }> = {
  ok: { cls: "bg-ok/10 border-ok/30", iconCls: "text-ok", icon: CircleCheck },
  warning: { cls: "bg-warn/15 border-warn/40", iconCls: "text-warn", icon: TriangleAlert },
  serious: { cls: "bg-serious/15 border-serious/40", iconCls: "text-serious", icon: OctagonAlert },
  critical: { cls: "bg-crit/10 border-crit/30", iconCls: "text-crit", icon: OctagonX },
  neutral: { cls: "bg-surface-2 border-line", iconCls: "text-ink-3", icon: Minus },
};

/** Status is always icon + label + tint — the status colours alone are too faint on light. */
export function StatusChip({
  tone,
  label,
  icon,
  className,
}: {
  tone: StatusChipTone;
  label: string;
  icon?: ReactNode;
  className?: string;
}) {
  const s = STATUS_CHIP[tone];
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-px text-2xs font-medium text-ink",
        s.cls,
        className,
      )}
    >
      <span className={clsx("inline-flex shrink-0", s.iconCls)} aria-hidden>
        {icon ?? createElement(s.icon, { className: "h-3 w-3" })}
      </span>
      {label}
    </span>
  );
}

/** Status colour shared by orders, agents and debates so one word reads the same everywhere. */
export function statusTone(status: string | null | undefined): string {
  const s = (status ?? "").toUpperCase();
  if (["FILLED", "RUNNING", "APPROVED", "COMPLETED", "HEALTHY", "OK"].includes(s)) return "good";
  if (["REJECTED", "CANCELLED", "CRASHED", "FAILED", "ERROR", "STOPPED"].includes(s)) return "bad";
  if (["PENDING", "IN_PROGRESS", "SUBMITTED", "PENDING_APPROVAL", "DEGRADED"].includes(s))
    return "warn";
  return "neutral";
}

/** Data table. Column 0 is left-aligned and the rest right-aligned unless `align` says otherwise;
 *  pass `onSort` to make headers clickable (`sortCol`/`sortDir` drive aria-sort). */
export function Table({
  head,
  children,
  className,
  align,
  onSort,
  sortCol,
  sortDir,
}: {
  head: ReactNode[];
  children: ReactNode;
  className?: string;
  align?: ("left" | "right")[];
  onSort?: (col: number) => void;
  sortCol?: number;
  sortDir?: "asc" | "desc";
}) {
  return (
    <div className={clsx("overflow-x-auto", className)}>
      <table className="w-full border-collapse">
        <thead className="sticky top-0 z-10 bg-surface">
          <tr className="border-b border-line">
            {head.map((cell, i) => {
              const right = (align?.[i] ?? (i > 0 ? "right" : "left")) === "right";
              const sorted = sortCol === i ? sortDir : undefined;
              return (
                <th
                  key={i}
                  className={clsx("th", right && "text-right")}
                  aria-sort={
                    onSort ? (sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none") : undefined
                  }
                >
                  {onSort ? (
                    <button
                      type="button"
                      onClick={() => onSort(i)}
                      className="inline-flex items-center gap-0.5 uppercase hover:text-ink"
                    >
                      {cell}
                      {sorted && <span aria-hidden>{sorted === "asc" ? "▲" : "▼"}</span>}
                    </button>
                  ) : (
                    cell
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
    </div>
  );
}

export function Empty({ message, hint }: { message: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1.5 px-4 py-10 text-center">
      <Inbox className="h-4 w-4 text-ink-3" aria-hidden />
      <p className="text-sm text-ink-2">{message}</p>
      {hint && <p className="max-w-sm text-xs text-ink-3">{hint}</p>}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 px-4 py-10 text-xs text-ink-3" role="status">
      <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div
      className="flex items-start gap-2 rounded border border-crit/30 bg-crit/10 px-3 py-2 text-sm text-ink"
      role="alert"
    >
      <OctagonAlert className="mt-0.5 h-4 w-4 shrink-0 text-crit" aria-hidden />
      <span>{message}</span>
    </div>
  );
}

/** Rendered output of a REPL command — the same text the terminal would print. */
export function CommandEcho({
  html,
  text,
  onDismiss,
}: {
  html?: string;
  text?: string;
  onDismiss?: () => void;
}) {
  if (!html && !text) return null;
  return (
    <div className="relative rounded border border-line bg-surface-2 px-3 py-2 pr-8">
      {html ? (
        <div
          className="rich-output font-mono text-xs leading-relaxed text-ink"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      ) : (
        <pre className="whitespace-pre-wrap font-mono text-xs text-ink">{text}</pre>
      )}
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="absolute right-2 top-2 rounded p-0.5 text-ink-3 hover:bg-surface hover:text-ink"
          title="Dismiss"
          aria-label="Dismiss"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold text-ink">{title}</h1>
        {subtitle && <p className="mt-0.5 text-xs text-ink-3">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

/** Status dot. Accepts the statusTone words (good/bad/warn) and the StatusChip tones. */
export function Dot({ tone = "neutral", pulse }: { tone?: string; pulse?: boolean }) {
  const colour =
    tone === "good" || tone === "ok"
      ? "bg-ok"
      : tone === "bad" || tone === "critical"
        ? "bg-crit"
        : tone === "warn" || tone === "warning"
          ? "bg-warn"
          : tone === "serious"
            ? "bg-serious"
            : "bg-ink-3";
  return (
    <span
      className={clsx("inline-block h-1.5 w-1.5 shrink-0 rounded-full", colour, pulse && "animate-pulse-dot")}
    />
  );
}

/** Compact pill group for ranges and tabs. `activeClassName` lets e.g. buy/sell tint when chosen. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  size = "sm",
  ariaLabel,
  className,
}: {
  options: { value: T; label: ReactNode; activeClassName?: string }[];
  value: T;
  onChange: (value: T) => void;
  size?: "sm" | "md";
  ariaLabel: string;
  className?: string;
}) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={clsx("no-drag inline-flex rounded border border-line bg-surface-2 p-0.5", className)}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(o.value)}
            className={clsx(
              "rounded-[3px] border font-medium transition-colors duration-100",
              size === "sm" ? "h-5 px-2 text-2xs" : "h-6 px-2.5 text-xs",
              active
                ? clsx("border-line bg-surface", o.activeClassName ?? "text-ink")
                : "border-transparent text-ink-2 hover:text-ink",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Toggle({
  on,
  onChange,
  disabled,
  label,
}: {
  on: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={clsx(
        "relative h-4 w-7 shrink-0 rounded-full transition-colors duration-100 disabled:opacity-50",
        on ? "bg-accent-strong" : "bg-ink-3",
      )}
    >
      <span
        className={clsx(
          "absolute top-0.5 h-3 w-3 rounded-full bg-white",
          on ? "left-[14px]" : "left-0.5",
        )}
      />
    </button>
  );
}

/** Icon-only button. `label` becomes the aria-label and tooltip; `pressed` makes it a toggle. */
export function IconButton({
  label,
  icon,
  onClick,
  pressed,
  size = "md",
  disabled,
  className,
}: {
  label: string;
  icon: LucideIcon | ReactElement;
  onClick?: () => void;
  pressed?: boolean;
  size?: "sm" | "md";
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      aria-pressed={pressed}
      title={label}
      className={clsx(
        "no-drag inline-flex shrink-0 items-center justify-center rounded transition-colors duration-100 hover:bg-surface-2 hover:text-ink disabled:opacity-50",
        size === "sm" ? "h-6 w-6" : "h-7 w-7",
        pressed ? "bg-surface-2 text-ink" : "text-ink-3",
        className,
      )}
    >
      {isValidElement(icon)
        ? icon
        : createElement(icon as LucideIcon, { className: size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4" })}
    </button>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 7CF1D7855BC7 - verify with scripts/authorship.py verify
