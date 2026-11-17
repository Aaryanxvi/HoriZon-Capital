import { HBarList, StatTile } from "@/components/charts";
import { Card, Empty } from "@/components/ui";
import { dateTime, money, num, timeAgo } from "@/lib/format";
import { useCostsInsights, type CostRow, type CostsInsights } from "@/lib/insights-api";
import { TabFrame } from "./shared";

export function CostsTab() {
  return (
    <TabFrame q={useCostsInsights()} label="costs">
      {(d) => <CostsBody d={d} />}
    </TabFrame>
  );
}

const bars = (rows: CostRow[]) =>
  rows.map((r) => ({ key: r.key, label: r.key, sublabel: `${r.calls} calls · ${num(r.tokens / 1000, 0)}k tok`, value: r.cost }));

function CostsBody({ d }: { d: CostsInsights }) {
  const { fills, llm } = d;
  const measured = fills.count - fills.slippage_unmeasured;

  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <StatTile
          label="LLM spend"
          value={llm.recorded ? money(llm.cost) : "—"}
          hint={llm.recorded ? `${llm.calls} calls · ${dateTime(llm.first)} → ${dateTime(llm.last)}` : "usage not recorded"}
        />
        <StatTile
          label="LLM per debate"
          value={llm.recorded && llm.per_debate.value !== null ? money(llm.per_debate.value) : "—"}
          hint={llm.recorded ? `debate calls ÷ ${llm.per_debate.n} debates in that window` : undefined}
        />
        <StatTile
          label="LLM per filled order"
          value={llm.recorded && llm.per_filled_order.value !== null ? money(llm.per_filled_order.value) : "—"}
          hint={llm.recorded ? `all calls ÷ ${llm.per_filled_order.n} filled orders` : undefined}
        />
        <StatTile
          label="Commissions"
          value={money(fills.commission)}
          hint={`${fills.count} fills · ${money(fills.notional)} traded`}
        />
        <StatTile
          label="Recorded slippage"
          value={measured ? money(fills.slippage) : "—"}
          hint={
            fills.slippage_unmeasured
              ? `${fills.slippage_unmeasured} of ${fills.count} broker fills carry no arrival price — unmeasured`
              : `${fills.count} simulated fills`
          }
        />
      </div>

      {llm.recorded ? (
        <>
          <p className="text-xs text-ink-3">
            Last logged LLM call {timeAgo(llm.last)} ({dateTime(llm.last)}). {num(llm.input_tokens / 1000, 0)}k input ·{" "}
            {num(llm.output_tokens / 1000, 0)}k output tokens
            {llm.estimated_calls ? ` · ${llm.estimated_calls} calls priced by estimate` : ""}. Calls made after the
            last logged one are not in these totals.
          </p>
          <div className="grid gap-3 xl:grid-cols-2">
            <Card title="Spend by agent">
              <HBarList rows={bars(llm.by_agent)} format={money} />
            </Card>
            <Card title="Spend by model">
              <HBarList rows={bars(llm.by_model)} format={money} />
            </Card>
            <Card title="Spend by purpose">
              <HBarList rows={bars(llm.by_purpose)} format={money} />
            </Card>
            <Card title="Spend by day" subtitle="UTC">
              <HBarList rows={bars(llm.by_day)} format={money} maxRows={31} />
            </Card>
          </div>
        </>
      ) : (
        <Card>
          <Empty
            message="LLM usage is not recorded"
            hint="Token counts and cost per call are not logged in this database, so spend per agent, model or debate can't be shown."
          />
        </Card>
      )}
    </>
  );
}
