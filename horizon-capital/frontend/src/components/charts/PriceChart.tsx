import { useEffect, useRef } from "react";
import { createChart, ColorType, CrosshairMode } from "lightweight-charts";
import type { IChartApi, ISeriesApi, CandlestickData, Time } from "lightweight-charts";

interface RegimeZone {
  from: number;
  to: number;
  regime: "BULL" | "BEAR" | "HIGH_VOL" | "CRISIS";
}

interface TradeMarker {
  time: number;
  side: "buy" | "sell";
  price: number;
}

interface PriceChartProps {
  symbol?: string;
  height?: number;
}

const REGIME_COLORS = {
  BULL: "rgba(16, 185, 129, 0.06)",
  BEAR: "rgba(239, 68, 68, 0.06)",
  HIGH_VOL: "rgba(245, 158, 11, 0.06)",
  CRISIS: "rgba(139, 92, 246, 0.06)",
};

function generateCandleData(): CandlestickData[] {
  const data: CandlestickData[] = [];
  let basePrice = 22000;
  const now = Math.floor(Date.now() / 1000);
  const daySeconds = 86400;

  for (let i = 180; i >= 0; i--) {
    const time = (now - i * daySeconds) as Time;
    const open = basePrice + (Math.random() - 0.5) * 200;
    const close = open + (Math.random() - 0.45) * 300;
    const high = Math.max(open, close) + Math.random() * 150;
    const low = Math.min(open, close) - Math.random() * 150;
    data.push({ time, open, high, low, close });
    basePrice = close;
  }
  return data;
}

function generateRegimeZones(): RegimeZone[] {
  const regimes: ("BULL" | "BEAR" | "HIGH_VOL" | "CRISIS")[] = [
    "BULL", "BULL", "BULL", "HIGH_VOL", "BEAR", "BEAR", "CRISIS", "BEAR", "BULL", "BULL",
  ];
  const now = Math.floor(Date.now() / 1000);
  const daySeconds = 86400;
  const zones: RegimeZone[] = [];
  const chunkSize = 18;

  regimes.forEach((regime, i) => {
    zones.push({
      from: now - (180 - i * chunkSize) * daySeconds,
      to: now - (180 - (i + 1) * chunkSize) * daySeconds,
      regime,
    });
  });
  return zones;
}

function generateTradeMarkers(candleData: CandlestickData[]): TradeMarker[] {
  const markers: TradeMarker[] = [];
  for (let i = 20; i < candleData.length; i += Math.floor(Math.random() * 15) + 10) {
    const candle = candleData[i];
    markers.push({
      time: candle.time as number,
      side: Math.random() > 0.5 ? "buy" : "sell",
      price: candle.close,
    });
  }
  return markers;
}

export default function PriceChart({ symbol = "NIFTY 50", height = 400 }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "#111827" },
        textColor: "#6b7280",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#1f2937" },
        horzLines: { color: "#1f2937" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "#374151", width: 1, style: 2 },
        horzLine: { color: "#374151", width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: "#1f2937",
      },
      timeScale: {
        borderColor: "#1f2937",
        timeVisible: false,
      },
    });

    chartRef.current = chart;

    // Candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor: "#10b981",
      downColor: "#ef4444",
      borderUpColor: "#10b981",
      borderDownColor: "#ef4444",
      wickUpColor: "#10b981",
      wickDownColor: "#ef4444",
    });

    const candleData = generateCandleData();
    candleSeries.setData(candleData);

    // Trade markers
    const tradeMarkers = generateTradeMarkers(candleData);
    const markers = tradeMarkers.map((tm) => ({
      time: tm.time as Time,
      position: tm.side === "buy" ? ("belowBar" as const) : ("aboveBar" as const),
      color: tm.side === "buy" ? "#10b981" : "#ef4444",
      shape: tm.side === "buy" ? ("arrowUp" as const) : ("arrowDown" as const),
      text: tm.side === "buy" ? "B" : "S",
    }));
    candleSeries.setMarkers(markers);

    // Handle resize
    const resizeObserver = new ResizeObserver((entries) => {
      const { width } = entries[0].contentRect;
      chart.applyOptions({ width });
    });
    resizeObserver.observe(containerRef.current);

    chart.timeScale().fitContent();

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [height]);

  // Regime legend
  const regimeZones = generateRegimeZones();
  const currentRegime = regimeZones[regimeZones.length - 1]?.regime || "BULL";

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-white">{symbol}</h3>
          <p className="text-xs text-gray-500 mt-0.5">Candlestick with Regime Overlay</p>
        </div>
        <div className="flex items-center gap-3">
          {(["BULL", "BEAR", "HIGH_VOL", "CRISIS"] as const).map((r) => (
            <div key={r} className="flex items-center gap-1.5">
              <div
                className="w-2.5 h-2.5 rounded-sm"
                style={{
                  backgroundColor:
                    r === "BULL" ? "#10b981" :
                    r === "BEAR" ? "#ef4444" :
                    r === "HIGH_VOL" ? "#f59e0b" : "#8b5cf6",
                }}
              />
              <span className="text-[9px] text-gray-500">{r}</span>
            </div>
          ))}
          <div className="ml-2 px-2 py-0.5 rounded text-[10px] font-bold bg-accent-green/10 text-accent-green border border-accent-green/20">
            Current: {currentRegime}
          </div>
        </div>
      </div>
      <div ref={containerRef} className="rounded-lg overflow-hidden" />
    </div>
  );
}
