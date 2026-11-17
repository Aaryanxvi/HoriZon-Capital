import { HBarList, StatTile } from "@/components/charts";
import { Card, Empty, StatusChip, Table } from "@/components/ui";
import { useChartTheme } from "@/lib/colors";
import { compactMoney, money, num } from "@/lib/format";
import { useRiskInsights, type RiskInsights } from "@/lib/insights-api";
import { NumCell, pctOf, sampleNote, TabFrame } from "./shared";

export function RiskTab() {
  return (
    <TabFrame q={useRiskInsights()} label="risk">
      {(d) => <RiskBody d={d} />}
    </TabFrame>
  );
}

function RiskBody({ d }: { d: RiskInsights }) {
  const theme = useChartTheme();
  const { stops, concentration: c } = d;
  const noBars = d.positions.filter((p) => p.vol === null).map((p) => p.symbol);
  const worst = Math.max(...d.scenarios.map((s) => Math.abs(s.pnl ?? 0)), 1);
  const covered = d.positions.filter((p) => p.risk_share !== null);

  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <StatTile
          label="Loss if every stop hits"
          value={money(-stops.loss_if_all_hit)}
          hint={`${pctOf(stops.loss_if_all_hit / d.nav, 2)} of NAV · stopped positions only`}
          status={
            stops.unprotected_count
              ? { tone: "serious", label: `${stops.unprotected_count} without stop` }
              : undefined
          }
        />
        <StatTile
          label="Unprotected exposure"
          value={compactMoney(stops.unprotected_usd)}
          hint={`${pctOf(stops.unprotected_usd / d.nav, 1)} of NAV has no stop — loss is open-ended`}
        />
        <StatTile
          label="Book beta to SPY"
          value={d.book_beta.covered_usd ? num(d.book_beta.value, 2) : "—"}
          hint={`from ${compactMoney(d.book_beta.covered_usd)} of ${compactMoney(d.gross)} gross`}
        />
        <StatTile
          label="Portfolio vol (ann.)"
          value={d.port_vol.value === null ? "—" : pctOf(d.port_vol.value, 1)}
          hint={
            d.port_vol.value === null
              ? sampleNote(d.port_vol, "daily returns")
              : `${d.port_vol.n} days · ${compactMoney(d.risk_covered_usd)} of book`
          }
        />
        <StatTile
          label="Cash buffer"
          value={pctOf(d.cash_pct, 1)}
          hint={`${compactMoney(d.cash)} of ${compactMoney(d.nav)} NAV`}
        />
      </div>

      {noBars.length > 0 && (
        <p className="text-xs text-ink-3">
          No daily price history for {noBars.join(", ")} — their volatility, beta, liquidity and history
          replay are not modelled ({compactMoney(d.gross - d.risk_covered_usd)} of exposure). Figures below
          cover only positions with ≥ {d.assumptions.min_bars} daily bars.
        </p>
      )}

      <div className="grid gap-3 xl:grid-cols-2">
        <Card
          title="Stress scenarios"
          subtitle="Today's book · SPY shocks pass through each position's beta"
          bodyClassName="p-0"
        >
          <Table head={["Scenario", "P&L", "% NAV", "", "Not modelled"]} align={["left", "right", "right", "left", "right"]}>
            {d.scenarios.map((s) => (
              <tr key={s.key}>
                <td className="td">
                  <div className="text-sm text-ink">{s.label}</div>
                  {s.date && <div className="text-2xs text-ink-3">{s.key === "worst_week" ? "week to " : ""}{s.date}</div>}
                </td>
                <NumCell why={`needs ${d.assumptions.min_bars} daily bars`}>{s.pnl === null ? "—" : money(s.pnl)}</NumCell>
                <NumCell>{s.pnl === null ? "—" : pctOf(s.pnl / d.nav, 2)}</NumCell>
                <td className="td w-28">
                  <div
                    className="h-2.5 rounded-r-[3px]"
                    style={{ width: `${(Math.abs(s.pnl ?? 0) / worst) * 100}%`, background: theme.down }}
                  />
                </td>
                <NumCell>{s.unmodeled_usd ? compactMoney(s.unmodeled_usd) : "—"}</NumCell>
              </tr>
            ))}
          </Table>
          <p className="border-t border-line px-3 py-2 text-2xs text-ink-3">
            Historical rows replay the worst day / 5-day move since {d.replay_from ?? "—"} ({d.replay_days} days) on
            today's quantities. "Not modelled" exposure is excluded from that row's P&L, not assumed flat.
          </p>
        </Card>

        <Card title="Risk contribution" subtitle="Share of portfolio variance · tick = weight of NAV">
          {covered.length ? (
            <HBarList
              rows={covered
                .sort((a, b) => (b.risk_share ?? 0) - (a.risk_share ?? 0))
                .map((p) => ({
                  key: p.symbol,
                  label: p.symbol,
                  sublabel: `vol ${pctOf(p.vol, 0)}`,
                  value: (p.risk_share ?? 0) * 100,
                  marker: (p.weight ?? 0) * 100,
                  markerLabel: "weight",
                }))}
              format={(v) => `${num(v, 1)}%`}
            />
          ) : (
            <Empty
              message="No position has enough history"
              hint={`Risk contribution needs ${d.assumptions.min_bars} overlapping daily returns.`}
            />
          )}
          <div className="mt-3 grid grid-cols-4 gap-2 border-t border-line pt-3 text-xs">
            <Fig label="Largest" value={pctOf(c.top1, 1)} />
            <Fig label="Top 5" value={pctOf(c.top5, 1)} />
            <Fig label="HHI (gross)" value={num(c.hhi, 2)} />
            <Fig label="Effective N" value={`${num(c.effective_n, 1)} of ${c.count}`} />
          </div>
        </Card>
      </div>

      <Card
        title="Stops & liquidity"
        subtitle={`Days to exit at ${num(d.assumptions.participation * 100, 0)}% of ${d.assumptions.adv_days}-day average dollar volume`}
        bodyClassName="p-0"
      >
        <Table
          head={["Symbol", "Value", "Weight", "Stop", "To stop", "Loss at stop", "Vol", "β SPY", "ADV", "Days to exit", "Bars"]}
        >
          {d.positions.map((p) => (
            <tr key={p.symbol}>
              <td className="td">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-ink">{p.symbol}</span>
                  {p.stop === null && <StatusChip tone="serious" label="No stop" />}
                </div>
              </td>
              <NumCell>{money(p.market_value)}</NumCell>
              <NumCell>{pctOf(p.weight, 1)}</NumCell>
              <NumCell>{p.stop === null ? "—" : money(p.stop)}</NumCell>
              <NumCell>{p.stop_distance_pct === null ? "—" : `${num(p.stop_distance_pct, 1)}%`}</NumCell>
              <NumCell>{p.loss_at_stop === null ? "—" : money(-p.loss_at_stop)}</NumCell>
              <NumCell why={`${p.bars} of ${d.assumptions.min_bars} daily bars`}>{pctOf(p.vol, 0)}</NumCell>
              <NumCell why={`${p.bars} of ${d.assumptions.min_bars} daily bars`}>{num(p.beta, 2)}</NumCell>
              <NumCell why={`needs ${d.assumptions.adv_days} daily bars with volume`}>{compactMoney(p.adv_usd)}</NumCell>
              <NumCell why="no volume history">
                {p.days_to_exit === null ? "—" : p.days_to_exit < 0.01 ? "<0.01" : num(p.days_to_exit, 2)}
              </NumCell>
              <NumCell>
                <span title={p.last_bar ? `last daily bar ${p.last_bar}` : "no daily bars"}>{p.bars}</span>
              </NumCell>
            </tr>
          ))}
        </Table>
      </Card>
    </>
  );
}

function Fig({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-2xs uppercase tracking-wide text-ink-3">{label}</div>
      <div className="nums text-sm text-ink">{value}</div>
    </div>
  );
}
