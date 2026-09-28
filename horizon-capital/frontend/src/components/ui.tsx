// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-7CF1D7855BC7
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import clsx from "clsx";
import { AlertTriangle, Inbox, Loader2, X } from "lucide-react";
import type { ReactNode } from "react";

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
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="truncate text-sm font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="truncate text-xs text-soft">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={clsx(bodyClassName ?? "p-4")}>{children}</div>
    </section>
  );
}

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
    <div className="card px-4 py-3">
      <div className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-faint">
        {icon}
        {label}
      </div>
      <div className={clsx("nums mt-1.5 text-xl font-semibold text-ink", valueClass)}>
        {value}
      </div>
      {hint !== undefined && <div className="nums mt-0.5 text-xs text-soft">{hint}</div>}
    </div>
  );
}

const BADGE_TONES: Record<string, string> = {
  neutral: "bg-raised text-soft border-line",
  good: "bg-up/10 text-up border-up/20",
  bad: "bg-down/10 text-down border-down/20",
  warn: "bg-warn/10 text-warn border-warn/20",
  accent: "bg-clay/10 text-clay border-clay/20",
};

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: keyof typeof BADGE_TONES | string;
  className?: string;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide",
        BADGE_TONES[tone] ?? BADGE_TONES.neutral,
        className,
      )}
    >
      {children}
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

export function Table({
  head,
  children,
  className,
}: {
  head: ReactNode[];
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("overflow-x-auto", className)}>
      <table className="w-full border-collapse">
        <thead className="sticky top-0 bg-surface">
          <tr className="border-b border-line">
            {head.map((cell, i) => (
              <th key={i} className={clsx("th", i > 0 && "text-right")}>
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line/70">{children}</tbody>
      </table>
    </div>
  );
}

export function Empty({ message, hint }: { message: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-12 text-center">
      <Inbox className="h-5 w-5 text-faint" />
      <p className="text-sm text-soft">{message}</p>
      {hint && <p className="max-w-sm text-xs text-faint">{hint}</p>}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 px-4 py-12 text-sm text-soft">
      <Loader2 className="h-4 w-4 animate-spin" />
      {label}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-down/20 bg-down/5 px-3 py-2 text-sm text-down">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
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
    <div className="relative rounded-lg border border-line bg-raised px-3 py-2 pr-8">
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
          onClick={onDismiss}
          className="absolute right-2 top-2 rounded p-0.5 text-faint hover:bg-surface hover:text-ink"
          title="Dismiss"
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
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-soft">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Dot({ tone = "neutral", pulse }: { tone?: string; pulse?: boolean }) {
  const colour =
    tone === "good"
      ? "bg-up"
      : tone === "bad"
        ? "bg-down"
        : tone === "warn"
          ? "bg-warn"
          : "bg-faint";
  return (
    <span
      className={clsx("inline-block h-1.5 w-1.5 rounded-full", colour, pulse && "animate-pulse-dot")}
    />
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 7CF1D7855BC7 - verify with scripts/authorship.py verify
