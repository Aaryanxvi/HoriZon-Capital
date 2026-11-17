import { Card } from "@/components/ui";
import { num, pct } from "@/lib/format";
import { useBenchmarkInsights, type BenchmarkInsights } from "@/lib/insights-api";
import { GateTile, pctOf, TabFrame } from "./shared";

const signedPct = (v: number) => pct(v * 100, 2);
const ratio = (v: number) => num(v, 2);
const capture = (v: number) => `${num(v * 100, 0)}%`;

export function BenchmarkTab() {
  return (
    <TabFrame q={useBenchmarkInsights()} label="benchmark">
      {(d) => <BenchmarkBody d={d} />}
    </TabFrame>
  );
}

function BenchmarkBody({ d }: { d: BenchmarkInsights }) {
  return (
    <>
      <p className="text-xs text-ink-3">
        Daily NAV (last snapshot per day) against {d.symbol} closes on the days both exist
        {d.window ? `, ${d.window[0]} → ${d.window[1]}` : ""}: {d.days} overlapping daily returns from{" "}
        {d.nav_days} recorded NAV days. Days the engine was off have no NAV and drop out.
      </p>

      <Card title="Return vs benchmark" bodyClassName="grid gap-3 p-3 sm:grid-cols-3">
        <GateTile label="Portfolio return" g={d.portfolio_return} format={signedPct} unit="days" />
        <GateTile label={`${d.symbol} return`} g={d.benchmark_return} format={signedPct} unit="days" />
        <GateTile label="Excess return" g={d.excess_return} format={signedPct} unit="days" />
      </Card>

      <Card
        title="Relationship to the market"
        subtitle={`Annualised from daily returns · needs ${d.min_days} days`}
        bodyClassName="grid gap-3 p-3 sm:grid-cols-2 xl:grid-cols-5"
      >
        <GateTile label="Beta" g={d.beta} format={ratio} unit="days" />
        <GateTile label="Alpha (ann.)" g={d.alpha} format={signedPct} unit="days" />
        <GateTile label="Correlation" g={d.correlation} format={ratio} unit="days" />
        <GateTile label="Tracking error" g={d.tracking_error} format={(v) => pctOf(v, 1)} unit="days" />
        <GateTile label="Information ratio" g={d.information_ratio} format={ratio} unit="days" />
      </Card>

      <Card
        title="Capture"
        subtitle={`Average portfolio move on ${d.symbol} up / down days, as a share of ${d.symbol}'s · needs ${d.min_capture_days} of each`}
        bodyClassName="grid gap-3 p-3 sm:grid-cols-2"
      >
        <GateTile label="Up capture" g={d.up_capture} format={capture} unit="up days" />
        <GateTile label="Down capture" g={d.down_capture} format={capture} unit="down days" />
      </Card>
    </>
  );
}
