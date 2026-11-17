import { ChartCard, Histogram, StatTile } from "@/components/charts";
import { Card, Empty, Table } from "@/components/ui";
import { dateTime, money, num, pct, tone } from "@/lib/format";
import { useTradesInsights, type TradesInsights } from "@/lib/insights-api";
import { GateTile, NumCell, pctOf, TabFrame } from "./shared";

const signedMoney = (v: number) => `${v > 0 ? "+" : ""}${money(v)}`;

export function TradesTab() {
  return (
    <TabFrame q={useTradesInsights()} label="trades">
      {(d) => <TradesBody d={d} />}
    </TabFrame>
  );
}

function TradesBody({ d }: { d: TradesInsights }) {
  const s = d.stats;
  const holding = d.closed.map((t) => t.holding_days).filter((v): v is number => v !== null);

  return (
    <>
      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <StatTile
          label="Closed round trips"
          value={String(s.count)}
          hint={s.count ? `${signedMoney(s.total_pnl)} realised` : "FIFO-matched from recorded fills"}
        />
        <GateTile label="Win rate" g={s.win_rate} format={(v) => pctOf(v, 0)} unit="trades" />
        <GateTile label="Expectancy / trade" g={s.expectancy} format={signedMoney} unit="trades" />
        <GateTile label="Profit factor" g={s.profit_factor} format={(v) => `${num(v, 2)}×`} unit="trades" />
        <GateTile label="Avg win" g={s.avg_win} format={signedMoney} unit="trades" />
        <GateTile label="Avg loss" g={s.avg_loss} format={signedMoney} unit="trades" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <GateTile label="Longest win streak" g={s.max_win_streak} format={(v) => String(v)} unit="trades" />
        <GateTile label="Longest loss streak" g={s.max_loss_streak} format={(v) => String(v)} unit="trades" />
      </div>

      {d.unmatched_exits.length > 0 && (
        <Card
          title={`${d.unmatched_exits.length} exits without a recorded entry`}
          subtitle="Sold lots the broker sync brought in — no entry fill, so not counted as round trips"
          bodyClassName="p-0"
        >
          <Table head={["Symbol", "Qty", "Exit price", "Notional", "Filled"]}>
            {d.unmatched_exits.map((u) => (
              <tr key={`${u.symbol}-${u.filled_at}`}>
                <td className="td text-sm text-ink">{u.symbol}</td>
                <NumCell>{num(u.qty, 4)}</NumCell>
                <NumCell>{money(u.price)}</NumCell>
                <NumCell>{money(u.qty * u.price)}</NumCell>
                <NumCell>{dateTime(u.filled_at)}</NumCell>
              </tr>
            ))}
          </Table>
        </Card>
      )}

      <div className="grid gap-3 xl:grid-cols-3">
        <Card title="Closed trades" subtitle="MAE / MFE from daily highs and lows while held" className="xl:col-span-2" bodyClassName="p-0">
          {d.closed.length ? (
            <Table head={["Symbol", "Exit", "Qty", "Entry", "Exit px", "P&L", "Return", "Held", "MAE", "MFE"]}>
              {d.closed.map((t) => (
                <tr key={`${t.symbol}-${t.exit_at}`}>
                  <td className="td text-sm text-ink">{t.symbol}</td>
                  <NumCell>{dateTime(t.exit_at)}</NumCell>
                  <NumCell>{num(t.qty, 4)}</NumCell>
                  <NumCell>{money(t.entry_price)}</NumCell>
                  <NumCell>{money(t.exit_price)}</NumCell>
                  <td className={`td nums text-right ${tone(t.pnl)}`}>{signedMoney(t.pnl)}</td>
                  <NumCell>{pct(t.return_pct)}</NumCell>
                  <NumCell>{t.holding_days === null ? "—" : `${num(t.holding_days, 1)}d`}</NumCell>
                  <NumCell why="no daily bars inside the holding period">{pct(t.mae_pct, 1)}</NumCell>
                  <NumCell why="no daily bars inside the holding period">{pct(t.mfe_pct, 1)}</NumCell>
                </tr>
              ))}
            </Table>
          ) : (
            <Empty
              message="No closed round trips yet"
              hint="A round trip is a SELL fill matched against an earlier recorded BUY fill."
            />
          )}
        </Card>

        <ChartCard
          title="Holding period"
          subtitle="days per closed trade"
          empty={
            holding.length < d.min_trades
              ? { message: `${holding.length} of ${d.min_trades} trades needed`, hint: "A distribution of fewer trades is anecdote." }
              : null
          }
          table={{ columns: ["Symbol", "Held (days)"], rows: d.closed.map((t) => [t.symbol, num(t.holding_days, 1)]) }}
        >
          <Histogram values={holding} bins={10} format={(v) => `${num(v, 1)}d`} />
        </ChartCard>
      </div>

      <div className="grid gap-3 xl:grid-cols-3">
        <Card title="Open trades" subtitle="Age = since this book first recorded the position" className="xl:col-span-2" bodyClassName="p-0">
          {d.open.length ? (
            <Table head={["Symbol", "Qty", "Entry", "Price", "Value", "Unrealised", "Realised", "Age"]}>
              {d.open.map((o) => (
                <tr key={o.symbol}>
                  <td className="td text-sm text-ink">
                    {o.symbol}
                    {o.short && <span className="ml-1 text-2xs text-ink-3">short</span>}
                  </td>
                  <NumCell>{num(o.qty, 4)}</NumCell>
                  <NumCell>{money(o.entry_price)}</NumCell>
                  <NumCell>{money(o.price)}</NumCell>
                  <NumCell>{money(o.market_value)}</NumCell>
                  <td className={`td nums text-right ${tone(o.unrealized_pnl)}`}>{signedMoney(o.unrealized_pnl)}</td>
                  <td className={`td nums text-right ${tone(o.realized_pnl)}`}>{signedMoney(o.realized_pnl)}</td>
                  <NumCell>{o.age_days === null ? "—" : `${num(o.age_days, 1)}d`}</NumCell>
                </tr>
              ))}
            </Table>
          ) : (
            <Empty message="No open positions" />
          )}
        </Card>

        <Card title="Turnover" subtitle="Traded notional ÷ average NAV, per month" bodyClassName="p-0">
          {d.turnover.length ? (
            <Table head={["Month", "Fills", "Notional", "Turnover"]}>
              {d.turnover.map((m) => (
                <tr key={m.month}>
                  <td className="td text-sm text-ink">{m.month}</td>
                  <NumCell>{m.fills}</NumCell>
                  <NumCell>{money(m.notional)}</NumCell>
                  <NumCell why="no NAV snapshots that month">{m.turnover === null ? "—" : `${num(m.turnover, 2)}×`}</NumCell>
                </tr>
              ))}
            </Table>
          ) : (
            <Empty message="No fills yet" />
          )}
        </Card>
      </div>
    </>
  );
}
