import clsx from "clsx";
import { useState, type ReactNode } from "react";

import { ChartCard, HBarList, StatTile, VoteBar } from "@/components/charts";
import { PageHeader, Segmented, Table } from "@/components/ui";
import {
  HORIZONS,
  useDebateAnalytics,
  useExecutionQuality,
  useExposure,
  usePnlAttribution,
  useSignalQuality,
  type ForwardStats,
  type Horizon,
  type Sampled,
  type VoteCounts,
} from "@/lib/analysis-api";
import { INSIGHT_TABS } from "@/components/insights";
import { ApiError } from "@/lib/api";
import { useChartTheme, withAlpha, type ChartTheme } from "@/lib/colors";
import { dateTime, money, num, tone } from "@/lib/format";

// ---------------------------------------------------------------------------
// Formatting — every aggregate carries n; below its minimum it reads "—".
// ---------------------------------------------------------------------------

/** Signed percent from a FRACTION: 0.0123 → "+1.23%". */
const sPct = (v: number, d = 2) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(d)}%`;
const rate = (v: number) => `${(v * 100).toFixed(0)}%`;
const bps = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)} bps`;
const sMoney = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${money(Math.abs(v))}`;
const show = (v: number | null | undefined, f: (v: number) => string) => (v === null || v === undefined ? "—" : f(v));
const needs = (s: Sampled) => `${s.n} of ${s.min} needed`;
/** Value when the sample is big enough, else the honest gap. */
const sampled = (s: Sampled, f: (v: number) => string) => (s.value === null ? needs(s) : `${f(s.value)} · n=${s.n}`);

const CLASS_LABEL: Record<string, string> = {
  equity: "Equity",
  etf: "ETF",
  crypto: "Crypto",
  prediction: "Prediction market",
};

function failure(endpoint: string, e: unknown): string | null {
  if (!e) return null;
  const why = e instanceof ApiError ? `HTTP ${e.status}` : e instanceof Error ? e.message : "request failed";
  return `GET ${endpoint} failed (${why})`;
}

// ---------------------------------------------------------------------------
// Small marks this page needs that the chart kit does not have.
// ---------------------------------------------------------------------------

type DivRow = { key: string; label: string; sublabel?: string; value: number; text: string };

/** Signed horizontal bars from a shared zero; colour comes from the caller (polarity or nominal). */
function DivergingBars({ rows, color }: { rows: DivRow[]; color: (v: number) => string }) {
  const top = Math.max(...rows.map((r) => Math.abs(r.value)), 0);
  const signed = rows.some((r) => r.value < 0);
  const zero = signed ? 50 : 0; // % from the left
  const span = signed ? 50 : 100;
  return (
    <div className="flex flex-col">
      {rows.map((r) => {
        const w = top > 0 ? (Math.abs(r.value) / top) * span : 0;
        return (
          <div
            key={r.key}
            title={`${r.label}${r.sublabel ? ` (${r.sublabel})` : ""} · ${r.text}`}
            className="flex min-h-7 items-center gap-3 rounded px-1 transition-colors duration-100 hover:bg-surface-2"
          >
            <span className="w-32 shrink-0 py-0.5 leading-tight">
              <span className="block truncate text-sm text-ink">{r.label}</span>
              {r.sublabel && <span className="block truncate text-2xs text-ink-3">{r.sublabel}</span>}
            </span>
            <span className="relative h-7 flex-1">
              {signed && <span className="absolute bottom-0 top-0 w-px bg-line-strong" style={{ left: "50%" }} />}
              <span
                className={clsx("absolute top-1/2 h-3.5 -translate-y-1/2", r.value < 0 ? "rounded-l-[3px]" : "rounded-r-[3px]")}
                style={{
                  left: `${r.value < 0 ? zero - w : zero}%`,
                  width: `${w}%`,
                  background: color(r.value),
                }}
              />
            </span>
            <span className="nums w-28 shrink-0 text-right text-sm text-ink-2">{r.text}</span>
          </div>
        );
      })}
    </div>
  );
}

// Diverging: two non-status hues over the neutral midpoint (correlation is not good/bad).
function corrTint(v: number, t: ChartTheme): string {
  if (v === 0) return t.divergingMid;
  return withAlpha(v > 0 ? t.series[0] : t.series[1], 0.14 + 0.66 * Math.min(Math.abs(v), 1));
}

function CorrHeatmap({ symbols, matrix, n }: { symbols: string[]; matrix: (number | null)[][]; n: number[][] }) {
  const t = useChartTheme();
  const short = (s: string) => s.replace(/\.(NYSE|NASDAQ|US|POLY)$/, "");
  return (
    <div className="overflow-x-auto">
      <div className="grid gap-0.5" style={{ gridTemplateColumns: `6rem repeat(${symbols.length}, minmax(2.5rem, 1fr))` }}>
        <span />
        {symbols.map((s) => (
          <span key={s} className="truncate pb-1 text-center text-2xs text-ink-3">
            {short(s)}
          </span>
        ))}
        {symbols.map((a, i) => (
          <div key={a} className="contents">
            <span className="truncate pr-2 text-right text-xs leading-8 text-ink-2">{short(a)}</span>
            {symbols.map((b, j) => {
              const v = matrix[i][j];
              return (
                <span
                  key={b}
                  title={`${short(a)} × ${short(b)} · ${v === null ? `needs overlap (n=${n[i][j]})` : `${num(v, 2)} · n=${n[i][j]}`}`}
                  className="nums flex h-8 items-center justify-center rounded-[3px] text-2xs text-ink"
                  style={{ background: v === null ? t.surface2 : corrTint(v, t) }}
                >
                  {v === null ? "·" : num(v, 2)}
                </span>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mt-2 flex flex-wrap items-baseline gap-2">
      <h2 className="text-2xs font-semibold uppercase tracking-wide text-ink-3">{children}</h2>
      {hint && <span className="text-xs text-ink-3">{hint}</span>}
    </div>
  );
}

const SLEEVE_NOTE =
  "Sleeve inferred from asset class — signals are logged as one combined sleeve system, so equity sleeves cannot be split";

// ---------------------------------------------------------------------------
// 1. P&L attribution
// ---------------------------------------------------------------------------

function PnlSection() {
  const t = useChartTheme();
  const q = usePnlAttribution();
  const d = q.data;
  const err = failure("/api/desktop/analysis/pnl", q.error);
  const polarity = (v: number) => (v >= 0 ? t.up : t.down);
  const top = d?.positions.length ? [...d.positions].sort((a, b) => b.total - a.total)[0] : null;
  const contribution = (v: number | null) => show(v, (x) => sPct(x, 3));

  return (
    <>
      <SectionTitle hint={d?.base_at ? `against first recorded NAV ${money(d.base_nav)} on ${dateTime(d.base_at)}` : undefined}>
        P&L attribution
      </SectionTitle>
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatTile
          label="NAV change"
          value={<span className={tone(d?.nav_change)}>{show(d?.nav_change, sMoney)}</span>}
          hint={d?.nav_change != null && d.base_nav ? sPct(d.nav_change / d.base_nav, 3) : undefined}
        />
        <StatTile label="Explained by positions" value={show(d?.explained, sMoney)} hint="realised + unrealised" />
        <StatTile
          label="Unexplained"
          value={show(d?.unexplained, sMoney)}
          hint="fees, closed rows, cash moves"
        />
        <StatTile
          label="Top contributor"
          value={top ? top.symbol : "—"}
          hint={top ? `${sMoney(top.total)} · ${contribution(top.contribution)}` : undefined}
        />
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <ChartCard
          title="Contribution by position"
          subtitle="realised + unrealised, % of base NAV"
          isLoading={q.isLoading}
          error={err}
          empty={d && !d.positions.length ? { message: "No positions recorded yet" } : null}
          table={
            d && {
              columns: ["Symbol", "Class", "Realised", "Unrealised", "Total", "Contribution"],
              rows: [...d.positions].reverse().map((r) => [
                r.symbol,
                CLASS_LABEL[r.asset_class] ?? r.asset_class,
                sMoney(r.realized),
                sMoney(r.unrealized),
                sMoney(r.total),
                contribution(r.contribution),
              ]),
            }
          }
        >
          <DivergingBars
            color={polarity}
            rows={[...(d?.positions ?? [])].reverse().map((r) => ({
              key: r.symbol,
              label: r.symbol,
              sublabel: `${CLASS_LABEL[r.asset_class] ?? r.asset_class}${r.open ? "" : " · closed"}`,
              value: r.total,
              text: `${sMoney(r.total)} · ${contribution(r.contribution)}`,
            }))}
          />
        </ChartCard>
        <ChartCard
          title="Contribution by sleeve"
          subtitle={SLEEVE_NOTE}
          isLoading={q.isLoading}
          error={err}
          empty={d && !d.sleeves.length ? { message: "No positions recorded yet" } : null}
          table={
            d && {
              columns: ["Sleeve", "Positions", "Realised", "Unrealised", "Total", "Contribution"],
              rows: [...d.sleeves].reverse().map((s) => [
                s.sleeve,
                s.positions,
                sMoney(s.realized),
                sMoney(s.unrealized),
                sMoney(s.total),
                contribution(s.contribution),
              ]),
            }
          }
        >
          <DivergingBars
            color={polarity}
            rows={[...(d?.sleeves ?? [])].reverse().map((s) => ({
              key: s.sleeve,
              label: s.sleeve,
              sublabel: `${s.positions} position${s.positions === 1 ? "" : "s"}`,
              value: s.total,
              text: `${sMoney(s.total)} · ${contribution(s.contribution)}`,
            }))}
          />
        </ChartCard>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// 2. Exposure & correlation
// ---------------------------------------------------------------------------

function ExposureSection() {
  const t = useChartTheme();
  const q = useExposure();
  const d = q.data;
  const err = failure("/api/desktop/analysis/exposure", q.error);
  const ofNav = (v: number) => (d?.nav ? sPct(v / d.nav) : money(v));
  const corr = d?.correlation;
  const bestOverlap = corr ? Math.max(0, ...corr.n.flatMap((row, i) => row.filter((_, j) => j !== i))) : 0;
  const anyCorr = !!corr && corr.matrix.some((row, i) => row.some((v, j) => i !== j && v !== null));
  const bars = (rows: { name: string; value: number }[], label = (s: string) => s) =>
    rows.map((r) => ({ key: r.name, label: label(r.name), value: r.value, text: ofNav(r.value) }));

  return (
    <>
      <SectionTitle hint="beta and correlation from daily closes vs SPY">Exposure & correlation</SectionTitle>
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatTile label="Gross exposure" value={d ? ofNav(d.gross).replace("+", "") : "—"} hint={d ? money(d.gross) : undefined} />
        <StatTile label="Net exposure" value={d ? ofNav(d.net) : "—"} hint={d ? money(d.net) : undefined} />
        <StatTile
          label="Book beta to SPY"
          value={d ? show(d.book_beta.value, (v) => num(v, 2)) : "—"}
          hint={d ? (d.book_beta.value === null ? `${needs(d.book_beta)} daily NAV returns` : `n=${d.book_beta.n} days`) : undefined}
        />
        <StatTile label="Holdings" value={d ? d.holdings.length : "—"} />
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <ChartCard
          title="By asset class"
          subtitle="% of NAV"
          isLoading={q.isLoading}
          error={err}
          empty={d && !d.by_asset_class.length ? { message: "No open positions" } : null}
          table={d && { columns: ["Asset class", "Value", "% NAV"], rows: d.by_asset_class.map((r) => [CLASS_LABEL[r.name] ?? r.name, money(r.value), ofNav(r.value)]) }}
        >
          <DivergingBars color={() => t.series[0]} rows={bars(d?.by_asset_class ?? [], (n) => CLASS_LABEL[n] ?? n)} />
        </ChartCard>
        <ChartCard
          title="By sector"
          subtitle="GICS sector for S&P 500 names; others are Unknown"
          isLoading={q.isLoading}
          error={err}
          empty={d && !d.by_sector.length ? { message: "No open positions" } : null}
          table={d && { columns: ["Sector", "Value", "% NAV"], rows: d.by_sector.map((r) => [r.name, money(r.value), ofNav(r.value)]) }}
        >
          <DivergingBars color={() => t.series[0]} rows={bars(d?.by_sector ?? [])} />
        </ChartCard>
        <ChartCard title="Beta to SPY by holding" subtitle={d ? `needs ${d.correlation.min} overlapping daily returns` : undefined} isLoading={q.isLoading} error={err}>
          <Table head={["Symbol", "Class", "Weight", "Beta", "Sample"]}>
            {d?.holdings.map((h) => (
              <tr key={h.symbol}>
                <td className="td">{h.symbol}</td>
                <td className="td text-right text-ink-2">{CLASS_LABEL[h.asset_class] ?? h.asset_class}</td>
                <td className="td nums text-right">{show(h.weight, sPct)}</td>
                <td className="td nums text-right">{show(h.beta.value, (v) => num(v, 2))}</td>
                <td className="td nums text-right text-ink-3">{h.beta.value === null ? needs(h.beta) : `n=${h.beta.n}`}</td>
              </tr>
            ))}
          </Table>
        </ChartCard>
        <ChartCard
          title="Correlation of daily returns"
          subtitle={corr ? `min ${corr.min} overlapping days per pair` : undefined}
          isLoading={q.isLoading}
          error={err}
          empty={
            d && !anyCorr
              ? {
                  message: "Not enough overlapping daily history",
                  hint: `Best pair overlaps ${bestOverlap} of ${corr?.min ?? 20} days needed. Crypto and prediction-market holdings have no daily bars in the store yet.`,
                }
              : null
          }
          table={
            corr && {
              columns: ["Pair", "Correlation", "Days"],
              rows: corr.symbols.flatMap((a, i) =>
                corr.symbols.slice(i + 1).map((b, k) => [`${a} × ${b}`, show(corr.matrix[i][i + 1 + k], (v) => num(v, 2)), corr.n[i][i + 1 + k]]),
              ),
            }
          }
        >
          {corr && <CorrHeatmap symbols={corr.symbols} matrix={corr.matrix} n={corr.n} />}
        </ChartCard>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// 3. Debate analytics
// ---------------------------------------------------------------------------

function VoteRows({ rows }: { rows: VoteCounts[] }) {
  return (
    <div className="flex flex-col gap-3">
      {rows.map((r) => (
        <div key={r.name}>
          <div className="mb-1 text-sm text-ink">{r.name}</div>
          <VoteBar against={r.against} abstain={r.abstain} for_={r.for} error={r.error} />
        </div>
      ))}
    </div>
  );
}

const voteTable = (rows: VoteCounts[], first: string) => ({
  columns: [first, "For", "Against", "Abstain", "Error"],
  rows: rows.map((r) => [r.name, r.for, r.against, r.abstain, r.error]),
});

function ForwardTable({ groups, first }: { groups: [string, Record<Horizon, ForwardStats>][]; first: string }) {
  return (
    <Table head={[first, ...HORIZONS.map((h) => `${h} avg`), ...HORIZONS.map((h) => `${h} hit rate`)]}>
      {groups.map(([name, block]) => (
        <tr key={name}>
          <td className="td">{name}</td>
          {HORIZONS.map((h) => (
            <td key={h} className={clsx("td nums text-right", block[h].avg.value === null ? "text-ink-3" : tone(block[h].avg.value))}>
              {sampled(block[h].avg, sPct)}
            </td>
          ))}
          {HORIZONS.map((h) => (
            <td key={h} className={clsx("td nums text-right", block[h].hit_rate.value === null && "text-ink-3")}>
              {sampled(block[h].hit_rate, rate)}
            </td>
          ))}
        </tr>
      ))}
    </Table>
  );
}

function DebateSection() {
  const t = useChartTheme();
  const q = useDebateAnalytics();
  const d = q.data;
  const err = failure("/api/desktop/analysis/debates", q.error);
  const days = d?.by_day ?? [];
  const shownDays = days.filter((x) => x.rate.value !== null);
  const outcome = Object.entries(d?.outcome ?? {});
  const lastDebate = d?.sessions[d.sessions.length - 1]?.created_at;
  const noDebates = d && !d.total ? { message: "No completed debates yet" } : null;

  return (
    <>
      <SectionTitle hint="forward return = symbol's close-to-close move after the debate, signed by the proposed side">
        Debate analytics
      </SectionTitle>
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatTile label="Debates" value={d ? d.total : "—"} />
        <StatTile
          label="Approval rate"
          value={d ? show(d.approval_rate.value, rate) : "—"}
          hint={d ? (d.approval_rate.value === null ? needs(d.approval_rate) : `n=${d.approval_rate.n}`) : undefined}
        />
        <StatTile
          label="Round-2 vote flips"
          value={d ? show(d.round2_flips.value, rate) : "—"}
          hint={d ? (d.round2_flips.value === null ? needs(d.round2_flips) : `${d.round2_flips.flips} of ${d.round2_flips.n} seats FOR↔AGAINST`) : undefined}
        />
        <StatTile
          label="Approved, 5d forward"
          value={d?.outcome.APPROVED ? show(d.outcome.APPROVED["5d"].avg.value, sPct) : "—"}
          hint={d?.outcome.APPROVED ? (d.outcome.APPROVED["5d"].avg.value === null ? needs(d.outcome.APPROVED["5d"].avg) : `n=${d.outcome.APPROVED["5d"].avg.n}`) : "no forward closes yet"}
        />
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <ChartCard
          className="lg:col-span-2"
          title="Did approved trades make money?"
          subtitle={d?.last_close ? `daily closes through ${d.last_close}` : undefined}
          isLoading={q.isLoading}
          error={err}
          empty={
            noDebates ??
            (d && !outcome.length
              ? {
                  message: "No debate has a forward close yet",
                  hint: `Latest debate ${dateTime(lastDebate)}; latest daily close ${d.last_close ?? "none"}. Each horizon fills in once that many daily closes exist after the debate.`,
                }
              : null)
          }
          table={
            d && {
              columns: ["Debate", "Symbol", "Side", "Decision", "1d", "5d", "20d"],
              rows: [...d.sessions].reverse().map((s) => [
                dateTime(s.created_at),
                s.symbol,
                s.action,
                s.decision,
                show(s.fwd_1d, sPct),
                show(s.fwd_5d, sPct),
                show(s.fwd_20d, sPct),
              ]),
            }
          }
        >
          <ForwardTable groups={outcome} first="Decision" />
        </ChartCard>
        <ChartCard
          title="Approval rate by day"
          subtitle={days.length > shownDays.length ? `${days.length - shownDays.length} day(s) under ${days[0]?.rate.min} debates hidden` : undefined}
          isLoading={q.isLoading}
          error={err}
          empty={noDebates ?? (d && !shownDays.length ? { message: "No day has enough debates yet" } : null)}
          table={d && { columns: ["Date", "Approved", "Rejected", "Other", "Rate"], rows: days.map((x) => [x.date, x.approved, x.rejected, x.other, sampled(x.rate, rate)]) }}
        >
          <HBarList
            color={t.series[0]}
            max={1}
            format={rate}
            rows={shownDays.map((x) => ({
              key: x.date,
              label: x.date,
              sublabel: `${x.approved} of ${x.rate.n}`,
              value: x.rate.value ?? 0,
            }))}
          />
        </ChartCard>
        <ChartCard
          title="Round-2 flips"
          subtitle="round-2 roles rotate, so a flip can be the new role, not persuasion"
          isLoading={q.isLoading}
          error={err}
          empty={noDebates}
        >
          <div className="text-sm text-ink-2">
            {d && (
              <>
                <span className="nums text-ink">{d.round2_flips.flips}</span> of{" "}
                <span className="nums text-ink">{d.round2_flips.n}</span> seats that voted FOR or AGAINST in both rounds changed side
                {d.round2_flips.value !== null ? ` (${rate(d.round2_flips.value)}).` : ` — ${needs(d.round2_flips)}.`}
              </>
            )}
          </div>
        </ChartCard>
        <ChartCard
          title="Votes by role"
          subtitle="role argued, both rounds"
          isLoading={q.isLoading}
          error={err}
          empty={noDebates}
          table={d && voteTable(d.by_role, "Role")}
        >
          <VoteRows rows={d?.by_role ?? []} />
        </ChartCard>
        <ChartCard
          title="Votes by LLM provider"
          isLoading={q.isLoading}
          error={err}
          empty={noDebates}
          table={d && voteTable(d.by_provider, "Provider")}
        >
          <VoteRows rows={d?.by_provider ?? []} />
        </ChartCard>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// 4. Signal quality  ·  5. Execution quality
// ---------------------------------------------------------------------------

function SignalSection() {
  const q = useSignalQuality();
  const d = q.data;
  return (
    <>
      <SectionTitle hint={SLEEVE_NOTE}>Signal quality</SectionTitle>
      <ChartCard
        title="Forward return after each signal"
        subtitle={d?.last_close ? `signed by direction · daily closes through ${d.last_close}` : undefined}
        isLoading={q.isLoading}
        error={failure("/api/desktop/analysis/signals", q.error)}
        empty={d && !d.sleeves.length ? { message: "No signals recorded yet" } : null}
      >
        <ForwardTable
          groups={(d?.sleeves ?? []).map((s) => [`${s.sleeve} · ${s.signals} signal${s.signals === 1 ? "" : "s"}`, s])}
          first="Sleeve"
        />
      </ChartCard>
    </>
  );
}

function ExecutionSection() {
  const q = useExecutionQuality();
  const d = q.data;
  return (
    <>
      <SectionTitle hint="positive bps = paid more than the reference price (a cost) on either side">Execution quality</SectionTitle>
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {d?.by_broker.map((b) => (
          <StatTile
            key={b.broker}
            label={`${b.broker} · vs arrival`}
            value={show(b.arrival_bps.value, bps)}
            hint={b.arrival_bps.value === null ? `${needs(b.arrival_bps)} · ${b.fills} fills` : `n=${b.arrival_bps.n} of ${b.fills} fills`}
          />
        ))}
      </div>
      <ChartCard
        title="Fills vs reference price"
        subtitle={d ? `arrival = last 1-min bar at order time, decision = at signal time; bars older than ${d.max_quote_age_s / 60} min are not used` : undefined}
        isLoading={q.isLoading}
        error={failure("/api/desktop/analysis/execution", q.error)}
        empty={d && !d.fills.length ? { message: "No fills yet" } : null}
      >
        <Table head={["Filled", "Symbol", "Side", "Broker", "Fill", "Arrival", "vs arrival", "Decision", "vs decision"]} align={["left", "left", "left", "left"]}>
          {d?.fills.map((f, i) => (
            <tr key={i}>
              <td className="td whitespace-nowrap text-xs text-ink-2">{dateTime(f.filled_at)}</td>
              <td className="td">{f.symbol}</td>
              <td className="td">{f.side}</td>
              <td className="td text-ink-2">{f.broker}</td>
              <td className="td nums text-right">{money(f.fill_price)}</td>
              <td className="td nums text-right">{show(f.arrival_price, money)}</td>
              <td className="td nums text-right">{show(f.arrival_bps, bps)}</td>
              <td className="td nums text-right">{show(f.decision_price, money)}</td>
              <td className="td nums text-right">{show(f.decision_bps, bps)}</td>
            </tr>
          ))}
        </Table>
      </ChartCard>
    </>
  );
}

// Append a tab here in one line; `render` mounts only while its tab is selected.
const TABS: { key: string; label: string; render: () => ReactNode }[] = [
  { key: "attribution", label: "Attribution", render: () => <PnlSection /> },
  { key: "exposure", label: "Exposure", render: () => <ExposureSection /> },
  {
    key: "decisions",
    label: "Decisions",
    render: () => (
      <>
        <DebateSection />
        <SignalSection />
      </>
    ),
  },
  { key: "execution", label: "Execution", render: () => <ExecutionSection /> },
  ...INSIGHT_TABS,
];
const TAB_KEY = "horizon-analysis-tab";

function storedTab(): string {
  try {
    const v = localStorage.getItem(TAB_KEY);
    return TABS.some((t) => t.key === v) ? v! : TABS[0].key;
  } catch {
    return TABS[0].key;
  }
}

export default function AnalysisPage() {
  const [tab, setTab] = useState(storedTab);
  const pick = (key: string) => {
    setTab(key);
    try {
      localStorage.setItem(TAB_KEY, key);
    } catch {
      // per-viewer convenience only
    }
  };
  const active = TABS.find((t) => t.key === tab) ?? TABS[0];
  return (
    <>
      <PageHeader title="Analysis" subtitle="What is making or losing money, and why. Metrics below their minimum sample read “—”." />
      <div className="flex flex-col gap-3">
        <Segmented
          options={TABS.map((t) => ({ value: t.key, label: t.label }))}
          value={active.key}
          onChange={pick}
          size="md"
          ariaLabel="Analysis section"
          className="self-start"
        />
        {active.render()}
      </div>
    </>
  );
}
