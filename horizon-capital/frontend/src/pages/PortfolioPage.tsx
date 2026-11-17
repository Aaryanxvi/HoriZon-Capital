// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-C419CE29E10B
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useState } from "react";

import { ChartCard, HBarList, StatTile } from "@/components/charts";
import { Card, Empty, ErrorNote, Loading, PageHeader, Table } from "@/components/ui";
import { useOverview, usePositions, useRisk, type Position } from "@/lib/api";
import { useChartTheme } from "@/lib/colors";
import { money, num, pct, timeAgo } from "@/lib/format";
import { allocationRows, exposure, isShort } from "@/lib/portfolio";

const HEAD = ["Symbol", "Qty", "Entry", "Last", "Value", "Weight", "Unrealised", "Stop", "Updated"];
// Sort key per column; Value and Weight both sort by |market value|.
const SORT_KEY: ((p: Position) => number | string)[] = [
  (p) => p.symbol,
  (p) => p.quantity,
  (p) => p.avg_entry_price,
  (p) => p.current_price,
  (p) => Math.abs(p.market_value),
  (p) => Math.abs(p.market_value),
  (p) => p.unrealized_pnl,
  (p) => p.stop_loss_price ?? -Infinity,
  (p) => p.updated_at ?? "",
];

const weightFmt = (v: number) => `${num(v, 1)}%`;
const signedTimes = (v: number) => `${v >= 0 ? "+" : "−"}${num(Math.abs(v), 2)}×`;

export default function PortfolioPage() {
  const theme = useChartTheme();
  const positionsQ = usePositions();
  const overviewQ = useOverview();
  const { data: risk } = useRisk();
  const [sort, setSort] = useState<{ col: number; dir: "asc" | "desc" }>({ col: 4, dir: "desc" });

  const positions = positionsQ.data?.positions ?? [];
  const overview = overviewQ.data;
  const nav = overview?.nav ?? 0;
  const cash = overview?.cash_usd ?? 0;
  const limit = risk?.limits.max_position_pct ?? null;
  const ready = !!positionsQ.data && !!overview;

  const invested = positions.reduce((sum, p) => sum + Math.abs(p.market_value), 0);
  const unrealised = positions.reduce((sum, p) => sum + p.unrealized_pnl, 0);
  const exp = exposure(positions, nav);
  const allocation = allocationRows(positions, nav, cash, limit);

  const weight = (p: Position) => (nav > 0 ? (Math.abs(p.market_value) / nav) * 100 : 0);
  // Inline weight bars span 0..1.25 × limit (as in Bullet) so a breach visibly passes the tick.
  const barMax = limit ? limit * 1.25 : Math.max(0, ...positions.map(weight));
  const barPos = (v: number) => `${barMax > 0 ? Math.min(Math.max(v / barMax, 0), 1) * 100 : 0}%`;

  const key = SORT_KEY[sort.col];
  const sign = sort.dir === "asc" ? 1 : -1;
  const sorted = [...positions].sort((a, b) => {
    const x = key(a);
    const y = key(b);
    return (x < y ? -1 : x > y ? 1 : 0) * sign;
  });
  const onSort = (col: number) =>
    setSort((s) =>
      s.col === col ? { col, dir: s.dir === "asc" ? "desc" : "asc" } : { col, dir: col === 0 ? "asc" : "desc" },
    );

  const cashShown = Math.max(cash, 0);
  const investedShare = invested + cashShown > 0 ? (invested / (invested + cashShown)) * 100 : 0;

  return (
    <>
      <PageHeader
        title="Portfolio"
        subtitle={`${positions.length} open position${positions.length === 1 ? "" : "s"}`}
      />

      <div className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Invested" value={ready ? money(invested) : "—"} />
        <StatTile
          label="Cash"
          value={ready ? money(cash) : "—"}
          hint={nav > 0 ? `${num((cash / nav) * 100, 1)}% of NAV` : undefined}
        />
        <StatTile
          label="Unrealised P&L"
          value={ready ? money(unrealised) : "—"}
          delta={invested > 0 ? { value: (unrealised / invested) * 100, format: pct, label: "of invested" } : undefined}
        />
        <StatTile
          label="Gross exposure"
          value={ready && nav > 0 ? `${num(exp.gross, 2)}×` : "—"}
          hint={ready && nav > 0 ? `net ${signedTimes(exp.net)}` : undefined}
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="Positions" bodyClassName="">
          {positionsQ.isLoading ? (
            <Loading label="Loading positions" />
          ) : positionsQ.error ? (
            <div className="p-3">
              <ErrorNote message={positionsQ.error.message} />
            </div>
          ) : positions.length === 0 ? (
            <Empty
              message="No open positions"
              hint="Positions appear after the first fill — the strategy sleeves trade when a weight drifts more than 50 bps from target."
            />
          ) : (
            <Table head={HEAD} onSort={onSort} sortCol={sort.col} sortDir={sort.dir}>
              {sorted.map((p) => {
                const w = weight(p);
                // return_pct is the price move; flip it for shorts so it agrees with the P&L sign.
                const ret = isShort(p.side) ? -p.return_pct : p.return_pct;
                const dir = p.unrealized_pnl > 0 ? "text-up" : p.unrealized_pnl < 0 ? "text-down" : "text-ink-2";
                const glyph = p.unrealized_pnl > 0 ? "▲ " : p.unrealized_pnl < 0 ? "▼ " : "";
                return (
                  <tr key={`${p.symbol}-${p.exchange}-${p.side}`} className="row-hover">
                    <td className="td">
                      <div className="font-medium">{p.symbol}</div>
                      <div className="text-2xs uppercase text-ink-3">
                        {p.exchange} · {p.side}
                      </div>
                    </td>
                    <td className="td nums text-right">{num(p.quantity, 4)}</td>
                    <td className="td nums text-right">{money(p.avg_entry_price, p.currency)}</td>
                    <td className="td nums text-right">{money(p.current_price, p.currency)}</td>
                    <td className="td nums text-right">{money(p.market_value, p.currency)}</td>
                    <td className="td text-right">
                      <div
                        className="flex items-center justify-end gap-2"
                        title={`${weightFmt(w)} of NAV${limit !== null ? ` · limit ${weightFmt(limit)}` : ""}`}
                      >
                        <span className="nums text-xs">{nav > 0 ? weightFmt(w) : "—"}</span>
                        <span className="relative h-1 w-[60px] shrink-0 rounded-sm bg-surface-2" aria-hidden>
                          <span
                            className="absolute inset-y-0 left-0 rounded-sm"
                            style={{ width: barPos(w), background: theme.series[0] }}
                          />
                          {limit !== null && (
                            <span className="absolute -top-1 h-3 w-px bg-ink-3" style={{ left: barPos(limit) }} />
                          )}
                        </span>
                      </div>
                    </td>
                    <td className={`td nums text-right ${dir}`}>
                      <div>
                        {glyph}
                        {money(p.unrealized_pnl, p.currency)}
                      </div>
                      <div className="text-2xs">{pct(ret)}</div>
                    </td>
                    <td className="td nums text-right">
                      {p.stop_loss_price === null ? (
                        <span className="text-2xs text-ink-3">none</span>
                      ) : (
                        money(p.stop_loss_price, p.currency)
                      )}
                    </td>
                    <td className="td whitespace-nowrap text-right text-xs text-ink-2">{timeAgo(p.updated_at)}</td>
                  </tr>
                );
              })}
            </Table>
          )}
        </Card>

        <ChartCard
          title="Allocation"
          subtitle="% of NAV, incl. cash"
          isLoading={positionsQ.isLoading || overviewQ.isLoading}
          isFetching={positionsQ.isFetching || overviewQ.isFetching}
          error={overviewQ.error?.message ?? positionsQ.error?.message ?? null}
          empty={
            allocation.length
              ? null
              : {
                  message: "No NAV yet",
                  hint: "NAV appears once the portfolio agent writes its first snapshot (every minute while the engine runs).",
                }
          }
          table={{
            columns: ["Holding", "Value", "Weight"],
            rows: allocation.map((r) => [r.label, r.sublabel ?? "", weightFmt(r.value)]),
          }}
        >
          <HBarList rows={allocation} format={weightFmt} />
          {invested + cashShown > 0 && (
            <div className="mt-3 border-t border-line pt-3">
              <div className="mb-1.5 flex items-center justify-between gap-2 text-xs">
                <span className="inline-flex items-center gap-1.5 text-ink-2">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: theme.series[0] }} />
                  Invested <span className="nums text-ink">{num(investedShare, 1)}%</span>
                </span>
                <span className="inline-flex items-center gap-1.5 text-ink-2">
                  Cash <span className="nums text-ink">{num(100 - investedShare, 1)}%</span>
                  <span className="h-2.5 w-2.5 rounded-sm bg-line-strong" />
                </span>
              </div>
              <div
                className="flex h-2.5 gap-0.5 overflow-hidden rounded"
                role="img"
                aria-label={`Invested ${num(investedShare, 1)}%, cash ${num(100 - investedShare, 1)}%`}
              >
                {investedShare > 0 && <span style={{ width: `${investedShare}%`, background: theme.series[0] }} />}
                {investedShare < 100 && <span className="flex-1 bg-line-strong" />}
              </div>
              <div className="mt-1 flex justify-between text-2xs text-ink-3">
                <span className="nums">{money(invested)}</span>
                <span className="nums">{money(cash)}</span>
              </div>
            </div>
          )}
        </ChartCard>
      </div>
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token C419CE29E10B - verify with scripts/authorship.py verify
