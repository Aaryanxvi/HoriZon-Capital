// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-56AA5C3690C8
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import {
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";

import { Segmented } from "@/components/ui";
import { lwChartOptions, useChartTheme, withAlpha } from "@/lib/colors";
import { money, num } from "@/lib/format";
import type { HistoryBar, HistoryRange } from "@/hooks/useWatchlist";

const RANGES: HistoryRange[] = ["1M", "6M", "1Y", "5Y"];

/**
 * Daily candlesticks + volume for one symbol, with a crosshair OHLCV readout and
 * 1M/6M/1Y/5Y range buttons. Stateless about data: the parent fetches `bars`.
 */
export function SymbolChart({
  bars,
  range,
  onRangeChange,
  loading,
  height = 300,
}: {
  bars: HistoryBar[];
  range: HistoryRange;
  onRangeChange: (range: HistoryRange) => void;
  loading?: boolean;
  height?: number;
}) {
  const theme = useChartTheme();
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const [hover, setHover] = useState<HistoryBar | null>(null);

  const byTime = useMemo(() => new Map(bars.map((b) => [b.time, b])), [bars]);

  // Create once; theme and data are applied by the effects below.
  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const chart = createChart(el, { width: el.clientWidth, height });
    candleRef.current = chart.addCandlestickSeries({ priceLineVisible: false });
    volumeRef.current = chart.addHistogramSeries({
      priceScaleId: "vol",
      priceFormat: { type: "volume" },
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    chart.priceScale("right").applyOptions({ scaleMargins: { top: 0.08, bottom: 0.22 } });
    chartRef.current = chart;

    const ro = new ResizeObserver(([entry]) =>
      chart.applyOptions({ width: Math.floor(entry.contentRect.width) }),
    );
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = candleRef.current = volumeRef.current = null;
    };
  }, [height]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.applyOptions({ ...lwChartOptions(theme), height });
    candleRef.current?.applyOptions({
      upColor: theme.up,
      downColor: theme.down,
      wickUpColor: theme.up,
      wickDownColor: theme.down,
      borderVisible: false,
    });
  }, [theme, height]);

  useEffect(() => {
    const candles: CandlestickData[] = bars.map((b) => ({
      time: b.time as Time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    const volume: HistogramData[] = bars.map((b) => ({
      time: b.time as Time,
      value: b.volume,
      color: withAlpha(b.close >= b.open ? theme.up : theme.down, 0.35),
    }));
    candleRef.current?.setData(candles);
    volumeRef.current?.setData(volume);
    chartRef.current?.timeScale().fitContent();
  }, [bars, theme, height]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const onMove = (p: MouseEventParams<Time>) =>
      setHover(p.time !== undefined ? byTime.get(String(p.time)) ?? null : null);
    chart.subscribeCrosshairMove(onMove);
    return () => chart.unsubscribeCrosshairMove(onMove);
  }, [byTime]);

  const shown = hover ?? bars[bars.length - 1];
  const first = bars[0];
  const rangeChange = first && shown ? ((shown.close - first.close) / first.close) * 100 : null;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="nums flex flex-wrap gap-x-3 text-xs text-ink-2">
          {shown ? (
            <>
              <span className="text-ink-3">{shown.time}</span>
              <span>O {money(shown.open)}</span>
              <span>H {money(shown.high)}</span>
              <span>L {money(shown.low)}</span>
              <span className="text-ink">C {money(shown.close)}</span>
              <span>Vol {num(shown.volume, 0)}</span>
              {rangeChange !== null && (
                <span className={rangeChange >= 0 ? "text-up" : "text-down"}>
                  {rangeChange >= 0 ? "+" : ""}
                  {rangeChange.toFixed(2)}% over {range}
                </span>
              )}
            </>
          ) : (
            <span className="text-ink-3">{loading ? "Loading history" : "No price history"}</span>
          )}
        </div>
        <Segmented
          ariaLabel="Chart range"
          options={RANGES.map((r) => ({ value: r, label: r }))}
          value={range}
          onChange={onRangeChange}
        />
      </div>
      <div
        ref={hostRef}
        className={loading ? "opacity-60 transition-opacity" : "transition-opacity"}
        style={{ height }}
      />
    </div>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 56AA5C3690C8 - verify with scripts/authorship.py verify
