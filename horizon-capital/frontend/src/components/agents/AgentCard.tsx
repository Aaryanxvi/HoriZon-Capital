// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-869547CF1321
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Pause, Play, Clock, Activity, ChevronDown, ChevronUp } from "lucide-react";
import clsx from "clsx";
import PixelAgent from "./PixelAgent";
import type { PixelAgentState } from "./PixelAgentGrid";

interface AgentCardProps {
  agent: PixelAgentState;
  onPause?: (id: string) => void;
  onResume?: (id: string) => void;
}

const STATUS_COLORS: Record<string, string> = {
  IDLE: "text-gray-500 bg-gray-500/10 border-gray-500/20",
  ANALYZING: "text-accent-blue bg-accent-blue/10 border-accent-blue/20",
  DEBATING: "text-cyan-400 bg-cyan-400/10 border-cyan-400/20",
  EXECUTING: "text-accent-yellow bg-accent-yellow/10 border-accent-yellow/20",
  ERROR: "text-accent-red bg-accent-red/10 border-accent-red/20",
};

// Mock activity log per agent
const MOCK_LOG = [
  { time: "14:32:01", msg: "Received market data update" },
  { time: "14:31:45", msg: "Generated signal: BUY RELIANCE (0.82)" },
  { time: "14:30:12", msg: "Completed analysis cycle" },
  { time: "14:28:55", msg: "Heartbeat sent" },
  { time: "14:25:00", msg: "Started new analysis cycle" },
];

export default function AgentCard({ agent, onPause, onResume }: AgentCardProps) {
  const [expanded, setExpanded] = useState(false);
  const uptimeHrs = Math.floor(agent.uptime / 3600);
  const uptimeMins = Math.floor((agent.uptime % 3600) / 60);
  const isPaused = agent.status === "IDLE";

  return (
    <motion.div
      layout
      className="card hover:border-accent-blue/20 transition-colors"
    >
      <div className="flex items-start gap-4">
        {/* Pixel avatar */}
        <div className="flex-shrink-0 pt-1">
          <PixelAgent
            agentId={agent.id}
            agentType={agent.type}
            status={agent.status}
            confidence={agent.confidence}
            size={3}
            showLabel={false}
          />
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-white truncate">{agent.name}</h3>
            <span
              className={clsx(
                "text-[10px] font-bold px-2 py-0.5 rounded border",
                STATUS_COLORS[agent.status]
              )}
            >
              {agent.status}
            </span>
          </div>

          <p className="text-xs text-gray-400 mt-1 capitalize">{agent.type} Agent</p>

          {/* Metrics row */}
          <div className="flex items-center gap-4 mt-3">
            <div className="flex items-center gap-1 text-[10px] text-gray-500">
              <Clock className="w-3 h-3" />
              <span>{uptimeHrs}h {uptimeMins}m</span>
            </div>
            <div className="flex items-center gap-1 text-[10px] text-gray-500">
              <Activity className="w-3 h-3" />
              <span>{Math.round(agent.confidence * 100)}% conf</span>
            </div>
          </div>

          {/* Last action */}
          <p className="text-[11px] text-gray-400 mt-2 truncate">
            {agent.lastAction}
          </p>

          {/* Controls */}
          <div className="flex items-center gap-2 mt-3">
            {isPaused ? (
              <button
                onClick={() => onResume?.(agent.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-accent-green/10 border border-accent-green/20 rounded-lg text-accent-green text-xs font-medium hover:bg-accent-green/20 transition-colors"
              >
                <Play className="w-3 h-3" />
                Resume
              </button>
            ) : (
              <button
                onClick={() => onPause?.(agent.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-accent-yellow/10 border border-accent-yellow/20 rounded-lg text-accent-yellow text-xs font-medium hover:bg-accent-yellow/20 transition-colors"
              >
                <Pause className="w-3 h-3" />
                Pause
              </button>
            )}

            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 px-3 py-1.5 bg-white/5 border border-horizon-border rounded-lg text-gray-400 text-xs hover:text-gray-200 transition-colors"
            >
              {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              Log
            </button>
          </div>
        </div>
      </div>

      {/* Expanded activity log */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="mt-4 pt-3 border-t border-horizon-border">
              <h4 className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">
                Activity Log
              </h4>
              <div className="space-y-1.5 max-h-32 overflow-y-auto">
                {MOCK_LOG.map((entry, i) => (
                  <div key={i} className="flex items-start gap-2 text-[10px]">
                    <span className="text-gray-600 font-mono flex-shrink-0">
                      {entry.time}
                    </span>
                    <span className="text-gray-400">{entry.msg}</span>
                  </div>
                ))}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 869547CF1321 - verify with scripts/authorship.py verify
