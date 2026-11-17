import { createElement } from "react";

import { BenchmarkTab } from "./BenchmarkTab";
import { CostsTab } from "./CostsTab";
import { HealthTab } from "./HealthTab";
import { RiskTab } from "./RiskTab";
import { TradesTab } from "./TradesTab";

// Extra Analysis-page tabs, in display order. Plain .ts, hence createElement over JSX.
export const INSIGHT_TABS: { key: string; label: string; render: () => JSX.Element }[] = [
  { key: "risk", label: "Risk", render: () => createElement(RiskTab) },
  { key: "trades", label: "Trades", render: () => createElement(TradesTab) },
  { key: "benchmark", label: "Benchmark", render: () => createElement(BenchmarkTab) },
  { key: "costs", label: "Costs", render: () => createElement(CostsTab) },
  { key: "health", label: "Health", render: () => createElement(HealthTab) },
];
