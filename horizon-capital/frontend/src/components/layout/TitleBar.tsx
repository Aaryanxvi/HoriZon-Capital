import { useState, useEffect } from "react";
import { Minus, Square, X } from "lucide-react";

interface HorizonAPI {
  isDesktop: boolean;
  platform: string;
  minimize: () => void;
  maximize: () => void;
  close: () => void;
}

const horizon = (window as unknown as { horizon?: HorizonAPI }).horizon;
const isDesktop = !!horizon?.isDesktop;

/**
 * Custom titlebar — Claude Desktop style.
 * Draggable, minimal, with traffic-light window controls.
 */
export default function TitleBar() {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);

  const timeStr = time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div
      className="h-9 flex items-center justify-between bg-horizon-dark border-b border-horizon-border/40 px-3 select-none flex-shrink-0"
      style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
    >
      {/* Left: logo + app name */}
      <div className="flex items-center gap-2">
        <div className="w-3 h-3 rounded-[3px] bg-accent-blue/70 flex items-center justify-center">
          <div className="w-[5px] h-[5px] bg-white/80 rounded-[1px]" />
        </div>
        <span className="text-[12px] font-medium text-gray-400 tracking-tight">
          Horizon Capital
        </span>
        <span className="text-[10px] text-gray-600 font-mono">
          {timeStr}
        </span>
      </div>

      {/* Right: window controls */}
      {isDesktop && (
        <div
          className="flex items-center"
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
        >
          <button
            onClick={() => horizon?.minimize()}
            className="w-10 h-9 flex items-center justify-center text-gray-600 hover:text-gray-300 hover:bg-white/[0.06] transition-colors"
          >
            <Minus className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => horizon?.maximize()}
            className="w-10 h-9 flex items-center justify-center text-gray-600 hover:text-gray-300 hover:bg-white/[0.06] transition-colors"
          >
            <Square className="w-3 h-3" />
          </button>
          <button
            onClick={() => horizon?.close()}
            className="w-10 h-9 flex items-center justify-center text-gray-600 hover:text-white hover:bg-red-500/80 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
}
