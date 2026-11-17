import { ChartCard, HBarList, type HBarRow } from "@/components/charts";
import { useRegime, type RegimeState } from "@/lib/brief-api";
import { useChartTheme } from "@/lib/colors";
import { timeAgo } from "@/lib/format";

// Semicircle dial over P(risk-on) from the SPY GMM regime model (quant/regime_hmm.py):
// 0 = fully risk-off (left), 1 = fully risk-on (right). Diverging from the 0.5 midpoint.
const CX = 100;
const CY = 100;
const R = 80;

const point = (p: number) => {
  const a = Math.PI * Math.min(Math.max(p, 0), 1);
  return [CX - R * Math.cos(a), CY - R * Math.sin(a)] as const;
};
const arc = (from: number, to: number) => {
  const [x1, y1] = point(Math.min(from, to));
  const [x2, y2] = point(Math.max(from, to));
  return `M ${x1} ${y1} A ${R} ${R} 0 0 1 ${x2} ${y2}`;
};

const LABEL: Record<RegimeState, string> = { RISK_ON: "Risk-on", RISK_OFF: "Risk-off" };
const weight = (v: number) => `${v.toFixed(1)}%`;

function researchStackResponse(state: RegimeState | null): string {
  if (state === "RISK_ON") return "risk book: TSMOM + quality";
  if (state === "RISK_OFF") return "defense: TLT / GLD";
  return "regime-gated";
}

export function RegimeGauge({ className }: { className?: string }) {
  const t = useChartTheme();
  const { data, isLoading, isFetching, error } = useRegime();
  const color = (s: RegimeState) => (s === "RISK_ON" ? t.series[0] : t.series[1]);

  const state = data?.state ?? null;
  const p = data?.p_risk_on ?? null;
  const history = data?.history ?? [];

  const rows: HBarRow[] = (data?.sleeves ?? [])
    .map((sl) => {
      const live = data?.sleeves_live && sl.signals.length
        ? sl.signals.map((s) => s.symbol.split(".")[0]).slice(0, 5).join(" · ")
        : null;
      return {
        key: sl.name,
        label: sl.name,
        sublabel:
          sl.name === "research_stack"
            ? researchStackResponse(state)
            : (live ?? `every ${sl.cadence_days}d${sl.last_refresh ? ` · refreshed ${timeAgo(sl.last_refresh)}` : ""}`),
        value: sl.weight * 100,
      };
    })
    .sort((a, b) => b.value - a.value);

  return (
    <ChartCard
      className={className}
      title="Market regime"
      subtitle={
        data?.available
          ? `SPY · GMM · ${data.source === "stored" ? "last logged" : "as of"} ${data.as_of?.slice(0, 10)}`
          : "SPY · GMM"
      }
      legend={[
        { label: "Risk-on", color: t.series[0], shape: "rect" },
        { label: "Risk-off", color: t.series[1], shape: "rect" },
      ]}
      table={
        history.length
          ? {
              columns: ["Date", "Regime", "P(risk-on)"],
              rows: history.map((h) => [h.date, LABEL[h.state], h.p_risk_on.toFixed(2)]),
            }
          : undefined
      }
      isLoading={isLoading}
      isFetching={isFetching && !isLoading}
      error={error ? `GET /api/desktop/brief/regime failed (${(error as Error).message})` : null}
    >
      <div className="flex flex-col gap-4">
        {state && p !== null ? (
          <div className="flex flex-col items-center">
            <svg viewBox="0 0 200 116" className="w-full max-w-[260px]" role="img">
              <title>{`${LABEL[state]} · P(risk-on) ${p.toFixed(2)}`}</title>
              <path d={arc(0, 1)} fill="none" stroke={t.divergingMid} strokeWidth={10} strokeLinecap="round" />
              <path d={arc(0.5, p)} fill="none" stroke={color(state)} strokeWidth={10} strokeLinecap="round" />
              <line x1={CX} y1={CY - R - 9} x2={CX} y2={CY - R + 9} stroke={t.border} strokeWidth={2} />
              <circle cx={point(p)[0]} cy={point(p)[1]} r={7} fill={color(state)} stroke={t.surface} strokeWidth={2} />
              <text x={CX} y={CY - 16} textAnchor="middle" fontSize={22} fontWeight={600} fill={t.text}>
                {LABEL[state]}
              </text>
              <text x={CX} y={CY} textAnchor="middle" fontSize={10} fill={t.text2}>
                {Math.round(Math.max(p, 1 - p) * 100)}% confidence
              </text>
              <text x={CX - R} y={CY + 16} textAnchor="middle" fontSize={9} fill={t.text3}>
                Off
              </text>
              <text x={CX + R} y={CY + 16} textAnchor="middle" fontSize={9} fill={t.text3}>
                On
              </text>
            </svg>
            <span className="nums text-2xs text-ink-3">P(risk-on) {p.toFixed(2)} · 0.5 = neutral</span>
          </div>
        ) : (
          <div className="py-4 text-center">
            <p className="text-sm text-ink-2">No regime reading yet</p>
            <p className="mt-1 text-xs text-ink-3">
              Needs ~280 SPY daily bars — the data worker backfills them once the engine runs.
            </p>
          </div>
        )}

        {history.length > 0 && (
          <div>
            <div className="mb-1 flex justify-between text-2xs text-ink-3">
              <span>{history[0].date}</span>
              <span>{history.length}d logged</span>
              <span>{history[history.length - 1].date}</span>
            </div>
            <div className="flex h-4 gap-[2px]">
              {history.map((h) => (
                <span
                  key={h.date}
                  className="max-w-[12px] flex-1 rounded-sm"
                  style={{ background: color(h.state) }}
                  title={`${h.date} · ${LABEL[h.state]} · P(risk-on) ${h.p_risk_on.toFixed(2)}`}
                />
              ))}
            </div>
          </div>
        )}

        <div>
          <div className="mb-1.5 flex items-baseline justify-between gap-2">
            <h3 className="text-2xs font-medium uppercase tracking-wide text-ink-3">Strategy mix</h3>
            <span className="text-2xs text-ink-3">
              {data?.sleeves_live ? "live targets · % of NAV" : "configured · engine off"}
            </span>
          </div>
          <HBarList rows={rows} format={weight} color={t.neutral} />
        </div>
      </div>
    </ChartCard>
  );
}
