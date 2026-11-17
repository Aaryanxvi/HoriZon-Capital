import clsx from "clsx";
import { LoaderCircle, Play } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import {
  ChartCard,
  StatTile,
  TimeSeries,
  type CrosshairReadout,
  type LegendItem,
  type TSSeries,
} from "@/components/charts";
import { Card, Empty, ErrorNote, Loading, PageHeader, StatusChip, Table } from "@/components/ui";
import {
  useRun,
  useRuns,
  useStartRun,
  useStrategies,
  type BacktestMetrics,
  type RunDetail,
  type RunSummary,
} from "@/lib/backtest-api";
import { useChartTheme } from "@/lib/colors";
import { compactMoney, money, num, tone } from "@/lib/format";
import { alignByDate, drawdown, indexTo100, type DatedValue } from "@/lib/series";

/** Signed percent from a FRACTION: 0.0123 → "+1.23%". */
const sPct = (v: number, d = 2) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(d)}%`;
const pp = (v: number) => `${Math.abs(v * 100).toFixed(2)} pp`;
const idx = (v: number) => v.toFixed(2);
const idxOrDash = (v: number | null | undefined) => (v == null ? "—" : idx(v));
const ddPct = (v: number) => {
  const text = Math.abs(v * 100).toFixed(1);
  return text === "0.0" ? "0.0%" : `−${text}%`;
};
const isoDay = (ms: number) => new Date(ms).toISOString().slice(0, 10);
const label = (s: string) => s.replace("_", " ");
const runName = (r: RunSummary) => `${label(r.strategy)} · ${r.symbols.join(", ")}`;

// --- form -------------------------------------------------------------------

function RunForm({ busy, elapsed, onStarted }: { busy: boolean; elapsed: number | null; onStarted: (id: string) => void }) {
  const strategies = useStrategies();
  const start = useStartRun();
  const today = isoDay(Date.now());
  const [form, setForm] = useState({
    strategy: "momentum",
    symbols: "AAPL",
    start: isoDay(Date.now() - 365 * 86_400_000),
    end: today,
    capital: "100000",
  });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const desc = strategies.data?.strategies.find((s) => s.name === form.strategy)?.description;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    start.mutate(
      {
        strategy: form.strategy,
        symbols: form.symbols.split(/[\s,]+/).filter(Boolean),
        start: form.start,
        end: form.end,
        capital: Number(form.capital),
      },
      { onSuccess: (r) => onStarted(r.id) },
    );
  };

  const field = "flex flex-col gap-1 text-2xs font-medium uppercase tracking-wide text-ink-3";
  return (
    <Card title="New backtest" subtitle="Simulated broker over daily bars — never touches the live book">
      <form onSubmit={submit} className="flex flex-col gap-3">
        <label className={field}>
          Strategy
          <select value={form.strategy} onChange={set("strategy")} className="input normal-case tracking-normal">
            {(strategies.data?.strategies ?? [{ name: "momentum", description: "" }]).map((s) => (
              <option key={s.name} value={s.name}>
                {label(s.name)}
              </option>
            ))}
          </select>
          {desc && <span className="text-xs font-normal normal-case tracking-normal text-ink-3">{desc}</span>}
        </label>
        <label className={field}>
          Symbols
          <input
            value={form.symbols}
            onChange={set("symbols")}
            placeholder="AAPL, MSFT"
            required
            className="input normal-case tracking-normal"
          />
          <span className="text-xs font-normal normal-case tracking-normal text-ink-3">
            Up to 10, capital split equally
          </span>
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className={field}>
            Start
            <input type="date" value={form.start} onChange={set("start")} min="2000-01-01" max={form.end} required className="input" />
          </label>
          <label className={field}>
            End
            <input type="date" value={form.end} onChange={set("end")} min={form.start} max={today} required className="input" />
          </label>
        </div>
        <label className={field}>
          Capital (USD)
          <input type="number" value={form.capital} onChange={set("capital")} min={1} step="any" required className="input nums" />
        </label>
        {start.error && <ErrorNote message={start.error.message} />}
        <button type="submit" disabled={busy || start.isPending} className="btn btn-primary">
          {busy ? (
            <>
              <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden />
              Running{elapsed != null && ` · ${elapsed.toFixed(1)}s`}
            </>
          ) : (
            <>
              <Play className="h-3.5 w-3.5" aria-hidden />
              Run backtest
            </>
          )}
        </button>
      </form>
    </Card>
  );
}

// --- past runs --------------------------------------------------------------

function RunList({
  runs,
  primary,
  compare,
  onOpen,
  onCompare,
}: {
  runs: RunSummary[];
  primary: string | null;
  compare: string | null;
  onOpen: (id: string) => void;
  onCompare: (id: string | null) => void;
}) {
  return (
    <Card title="Past runs" subtitle="Click to open · Compare overlays a second run" bodyClassName="max-h-[372px] overflow-auto">
      {runs.length === 0 ? (
        <Empty message="No backtests yet" hint="Runs are saved under ~/.horizon-capital/backtests." />
      ) : (
        <Table head={["Run", "Period", "Return", "Sharpe", ""]} align={["left", "left", "right", "right", "right"]}>
          {runs.map((r) => (
            <tr
              key={r.id}
              onClick={() => onOpen(r.id)}
              className={clsx("row-hover cursor-pointer", r.id === primary && "bg-surface-2")}
              aria-selected={r.id === primary}
            >
              <td className="td">
                <div className="flex items-center gap-1.5">
                  {r.id === primary && <span className="h-[3px] w-2.5 shrink-0 rounded-full bg-accent" aria-hidden />}
                  <span className="truncate font-medium capitalize">{runName(r)}</span>
                  {r.status === "running" && <StatusChip tone="neutral" label="running" />}
                  {r.status === "error" && <StatusChip tone="critical" label="failed" />}
                </div>
                <div className="text-xs text-ink-3">{compactMoney(r.capital)}</div>
              </td>
              <td className="td whitespace-nowrap text-xs text-ink-2">
                {r.start} → {r.end}
              </td>
              <td className={clsx("td nums text-right", tone(r.metrics?.total_return))}>
                {r.metrics ? sPct(r.metrics.total_return) : "—"}
              </td>
              <td className="td nums text-right">{r.metrics ? num(r.metrics.sharpe) : "—"}</td>
              <td className="td text-right">
                {r.id !== primary && r.status === "done" && (
                  <button
                    type="button"
                    aria-pressed={r.id === compare}
                    onClick={(e) => {
                      e.stopPropagation();
                      onCompare(r.id === compare ? null : r.id);
                    }}
                    className={clsx("btn h-6 px-2 text-xs", r.id === compare && "border-transparent bg-accent-strong text-accent-ink")}
                  >
                    {r.id === compare ? "Comparing" : "Compare"}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

// --- results ----------------------------------------------------------------

type Tile = { key: keyof BacktestMetrics; label: string; format: (v: number) => string; delta?: (v: number) => string; upIsGood?: boolean };

const TILES: Tile[] = [
  { key: "total_return", label: "Total return", format: sPct, delta: pp },
  { key: "cagr", label: "CAGR", format: sPct, delta: pp },
  { key: "sharpe", label: "Sharpe", format: (v) => num(v), delta: (v) => num(Math.abs(v)) },
  { key: "sortino", label: "Sortino", format: (v) => num(v), delta: (v) => num(Math.abs(v)) },
  { key: "max_drawdown", label: "Max drawdown", format: (v) => ddPct(-v), delta: pp, upIsGood: false },
  { key: "win_rate", label: "Win rate", format: (v) => `${(v * 100).toFixed(1)}%`, delta: pp },
  { key: "trades", label: "Trades", format: (v) => String(v) },
];

function Tiles({ a, b }: { a: BacktestMetrics; b: BacktestMetrics | null }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
      {TILES.map((t) => (
        <StatTile
          key={t.key}
          label={t.label}
          value={t.format(a[t.key])}
          delta={
            b && t.delta
              ? { value: a[t.key] - b[t.key], format: t.delta, upIsGood: t.upIsGood, label: "vs compared" }
              : undefined
          }
          hint={t.key === "win_rate" ? `${a.round_trips} closed` : t.key === "trades" && b ? `compared: ${b.trades}` : undefined}
        />
      ))}
    </div>
  );
}

const toTS = (pts: DatedValue[]) => pts.map((p) => ({ time: p.date, value: p.value }));

function EquityChart({ a, b }: { a: RunDetail; b: RunDetail | null }) {
  const t = useChartTheme();
  const [read, setRead] = useState<CrosshairReadout | null>(null);
  const [ddRead, setDdRead] = useState<number | null>(null);

  const d = useMemo(() => {
    const eq = (a.equity ?? []).map((p) => ({ date: p.date, value: p.value }));
    const spy = alignByDate(eq, (a.benchmark ?? []).map((p) => ({ date: p.date, value: p.close })));
    const dd = drawdown(eq.map((p) => p.value));
    return {
      a: toTS(indexTo100(eq)),
      spy: toTS(indexTo100(spy.map((x) => ({ date: x.date, value: x.b })))),
      b: b ? toTS(indexTo100((b.equity ?? []).map((p) => ({ date: p.date, value: p.value })))) : [],
      dd: eq.map((p, i) => ({ time: p.date, value: dd[i] })),
    };
  }, [a, b]);

  const main = useMemo<TSSeries[]>(
    () => [
      { id: "a", label: runName(a), kind: "line", data: d.a, color: t.accent, format: idx },
      ...(b ? [{ id: "b", label: runName(b), kind: "line" as const, data: d.b, color: t.series[1], format: idx }] : []),
      ...(d.spy.length ? [{ id: "spy", label: "SPY", kind: "line" as const, data: d.spy, color: t.neutral, format: idx }] : []),
    ],
    [a, b, d, t],
  );
  const ddSeries = useMemo<TSSeries[]>(
    () => [
      {
        id: "dd",
        label: "Drawdown",
        kind: "area",
        data: d.dd,
        color: t.down,
        fillColor: t.downFill,
        format: ddPct,
        scaleMargins: { top: 0.15, bottom: 0.1 },
      },
    ],
    [d.dd, t],
  );

  const legend: LegendItem[] = [
    { label: b ? "This run" : runName(a), color: t.accent, value: idxOrDash(read?.values.a) },
    ...(b ? [{ label: runName(b), color: t.series[1], value: idxOrDash(read?.values.b) }] : []),
    ...(d.spy.length ? [{ label: "SPY", color: t.neutral, value: idxOrDash(read?.values.spy) }] : []),
  ];
  const table = useMemo(() => {
    const spyAt = new Map(d.spy.map((p) => [p.time, p.value]));
    return {
      columns: ["Date", "Run idx", "SPY idx", "Drawdown"],
      rows: d.a.map((p, i) => [p.time, idx(p.value), idxOrDash(spyAt.get(p.time)), ddPct(d.dd[i].value)]).reverse(),
    };
  }, [d]);

  return (
    <ChartCard
      title="Equity vs SPY"
      subtitle={`Indexed to 100 at ${a.start}${d.spy.length ? "" : " · SPY history unavailable for these dates"}`}
      legend={legend}
      table={table}
      height={260 + 120 + 24}
    >
      <TimeSeries key={a.id} series={main} height={260} syncKey="backtest" onCrosshair={setRead} />
      <div className="mb-1 mt-2 flex items-baseline gap-2 text-2xs">
        <span className="font-medium uppercase tracking-wide text-ink-3">Drawdown</span>
        <span className="nums text-ink">{ddRead === null ? "—" : ddPct(ddRead)}</span>
      </div>
      <TimeSeries
        key={`${a.id}-dd`}
        series={ddSeries}
        height={120}
        syncKey="backtest"
        onCrosshair={(r) => setDdRead(r.values.dd ?? null)}
      />
    </ChartCard>
  );
}

function Trades({ run }: { run: RunDetail }) {
  const trades = run.trades ?? [];
  return (
    <Card title="Trades" subtitle={`${trades.length} fills · next-bar open, slippage + commission`} bodyClassName="max-h-[360px] overflow-auto">
      {trades.length === 0 ? (
        <Empty message="No trades" hint="The strategy never fired in this window — try a longer range." />
      ) : (
        <Table head={["Date", "Symbol", "Side", "Qty", "Price", "P&L"]} align={["left", "left", "left", "right", "right", "right"]}>
          {trades.map((tr, i) => (
            <tr key={i} className="row-hover">
              <td className="td nums">{tr.date}</td>
              <td className="td font-medium">{tr.symbol}</td>
              <td className={clsx("td text-xs font-medium", tr.side === "BUY" ? "text-up" : "text-down")}>{tr.side}</td>
              <td className="td nums text-right">{num(tr.quantity, 2)}</td>
              <td className="td nums text-right">{money(tr.price)}</td>
              <td className={clsx("td nums text-right", tr.side === "SELL" && tone(tr.pnl))}>
                {tr.side === "SELL" ? money(tr.pnl) : "—"}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

// --- page -------------------------------------------------------------------

export default function BacktestPage() {
  const runs = useRuns();
  const [selected, setSelected] = useState<string | null>(null);
  const [compare, setCompare] = useState<string | null>(null);
  const list = runs.data?.runs ?? [];
  const primaryId = selected ?? list[0]?.id ?? null;
  const a = useRun(primaryId);
  const b = useRun(compare && compare !== primaryId ? compare : null);
  const active = list.find((r) => r.id === runs.data?.active) ?? null;

  const open = (id: string) => {
    setSelected(id);
    if (id === compare) setCompare(null);
  };

  const run = a.data;
  const other = b.data?.status === "done" ? b.data : null;

  return (
    <>
      <PageHeader title="Backtest" subtitle="Replay daily bars through a strategy and compare against SPY" />
      <div className="flex flex-col gap-3">
        <div className="grid gap-3 lg:grid-cols-3">
          <RunForm
            busy={!!active}
            elapsed={active?.elapsed_s ?? null}
            onStarted={(id) => {
              setSelected(id);
              setCompare(null);
            }}
          />
          <div className="lg:col-span-2">
            {runs.isLoading ? (
              <Loading />
            ) : runs.error ? (
              <ErrorNote message={`GET /api/desktop/backtest/runs failed (${runs.error.message})`} />
            ) : (
              <RunList runs={list} primary={primaryId} compare={compare} onOpen={open} onCompare={setCompare} />
            )}
          </div>
        </div>

        {!primaryId ? null : a.isLoading || run?.status === "running" ? (
          <Card>
            <Loading
              label={run?.status === "running" ? `Running backtest · ${(run.elapsed_s ?? 0).toFixed(1)}s` : "Loading run"}
            />
          </Card>
        ) : a.error ? (
          <ErrorNote message={`Could not load run ${primaryId} (${a.error.message})`} />
        ) : run?.status === "error" ? (
          <ErrorNote message={`Backtest failed: ${run.error}`} />
        ) : run?.metrics ? (
          <>
            <Tiles a={run.metrics} b={other?.metrics ?? null} />
            <EquityChart a={run} b={other} />
            <Trades run={run} />
          </>
        ) : null}
      </div>
    </>
  );
}
