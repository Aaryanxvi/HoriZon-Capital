// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-70202286DC40
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { MessageCircle, ThumbsUp, ThumbsDown, Minus, CheckCircle2 } from "lucide-react";
import clsx from "clsx";
import PixelAgent from "./PixelAgent";
import type { AgentStatus } from "./PixelAgent";

interface DebateEntry {
  id: string;
  agentName: string;
  agentType: string;
  position: "bull" | "bear" | "neutral";
  argument: string;
  confidence: number;
}

interface DebateSessionData {
  id: string;
  topic: string;
  status: "active" | "concluded";
  consensus?: string;
  entries: DebateEntry[];
}

// Mock debate data
const MOCK_DEBATES: DebateSessionData[] = [
  {
    id: "d1",
    topic: "Should we increase NIFTY exposure given current regime?",
    status: "active",
    entries: [
      { id: "e1", agentName: "Alpha Seeker", agentType: "strategy", position: "bull", argument: "Momentum indicators are strongly positive. RSI at 62 with room to run. Breakout above 22,500 confirmed with volume.", confidence: 0.82 },
      { id: "e2", agentName: "Risk Guardian", agentType: "risk", position: "bear", argument: "VaR is approaching 85% of limit. Adding exposure increases concentration risk. Suggest waiting for pullback.", confidence: 0.75 },
      { id: "e3", agentName: "Sentiment Analyzer", agentType: "sentiment", position: "bull", argument: "Social sentiment is overwhelmingly positive. FII flows increasing. Global risk-on environment supports India.", confidence: 0.68 },
      { id: "e4", agentName: "Regime Detector", agentType: "regime", position: "neutral", argument: "Current regime is BULL but showing early signs of transition. Volatility clustering detected. Recommend measured approach.", confidence: 0.71 },
    ],
  },
  {
    id: "d2",
    topic: "RELIANCE entry at current levels",
    status: "concluded",
    consensus: "Approved with reduced size (0.5x conviction)",
    entries: [
      { id: "e5", agentName: "Alpha Seeker", agentType: "strategy", position: "bull", argument: "Strong earnings beat. Technical breakout pattern.", confidence: 0.88 },
      { id: "e6", agentName: "Risk Guardian", agentType: "risk", position: "bull", argument: "Position sizing within limits. Sector exposure acceptable.", confidence: 0.79 },
    ],
  },
];

const VOTE_ICON = {
  bull: ThumbsUp,
  bear: ThumbsDown,
  neutral: Minus,
};

const VOTE_COLOR = {
  bull: "text-accent-green bg-accent-green/10 border-accent-green/20",
  bear: "text-accent-red bg-accent-red/10 border-accent-red/20",
  neutral: "text-gray-400 bg-gray-400/10 border-gray-400/20",
};

interface DebateViewerProps {
  compact?: boolean;
}

export default function DebateViewer({ compact = false }: DebateViewerProps) {
  const [debates] = useState<DebateSessionData[]>(MOCK_DEBATES);
  const [selectedDebate, setSelectedDebate] = useState<string>(MOCK_DEBATES[0].id);
  const [visibleEntries, setVisibleEntries] = useState<number>(0);

  const active = debates.find((d) => d.id === selectedDebate);

  // Animate entries appearing one by one for active debates
  useEffect(() => {
    if (!active || active.status !== "active") {
      setVisibleEntries(active?.entries.length || 0);
      return;
    }
    setVisibleEntries(0);
    const timers: ReturnType<typeof setTimeout>[] = [];
    active.entries.forEach((_, i) => {
      timers.push(setTimeout(() => setVisibleEntries(i + 1), (i + 1) * 800));
    });
    return () => timers.forEach(clearTimeout);
  }, [selectedDebate, active]);

  if (!active) return null;

  const bullCount = active.entries.filter((e) => e.position === "bull").length;
  const bearCount = active.entries.filter((e) => e.position === "bear").length;
  const neutralCount = active.entries.filter((e) => e.position === "neutral").length;
  const total = active.entries.length;
  const consensusPct = total > 0 ? Math.max(bullCount, bearCount) / total : 0;

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <MessageCircle className="w-4 h-4 text-cyan-400" />
          <h3 className="text-sm font-semibold text-white">Agent Debates</h3>
        </div>

        {/* Tab selector */}
        <div className="flex gap-1">
          {debates.map((d) => (
            <button
              key={d.id}
              onClick={() => setSelectedDebate(d.id)}
              className={clsx(
                "px-2 py-1 text-[10px] rounded transition-colors",
                d.id === selectedDebate
                  ? "bg-accent-blue/20 text-accent-blue border border-accent-blue/20"
                  : "text-gray-500 hover:text-gray-300 border border-transparent"
              )}
            >
              {d.status === "active" ? "Active" : "Recent"}
            </button>
          ))}
        </div>
      </div>

      {/* Topic */}
      <div className="bg-horizon-darker rounded-lg p-3 mb-4 border border-horizon-border">
        <p className="text-xs text-gray-300">{active.topic}</p>
        {active.status === "concluded" && (
          <div className="flex items-center gap-2 mt-2">
            <CheckCircle2 className="w-3.5 h-3.5 text-accent-green" />
            <span className="text-[11px] text-accent-green">{active.consensus}</span>
          </div>
        )}
      </div>

      {/* Consensus meter */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] text-gray-500">Consensus</span>
          <div className="flex items-center gap-3 text-[10px]">
            <span className="text-accent-green">Bull: {bullCount}</span>
            <span className="text-accent-red">Bear: {bearCount}</span>
            <span className="text-gray-400">Neutral: {neutralCount}</span>
          </div>
        </div>
        <div className="h-2 bg-horizon-darker rounded-full overflow-hidden flex">
          <motion.div
            className="bg-accent-green h-full"
            animate={{ width: `${(bullCount / Math.max(total, 1)) * 100}%` }}
            transition={{ duration: 0.5 }}
          />
          <motion.div
            className="bg-gray-500 h-full"
            animate={{ width: `${(neutralCount / Math.max(total, 1)) * 100}%` }}
            transition={{ duration: 0.5 }}
          />
          <motion.div
            className="bg-accent-red h-full"
            animate={{ width: `${(bearCount / Math.max(total, 1)) * 100}%` }}
            transition={{ duration: 0.5 }}
          />
        </div>
        <div className="text-right mt-0.5">
          <span className="text-[9px] text-gray-600">
            {Math.round(consensusPct * 100)}% agreement
          </span>
        </div>
      </div>

      {/* Debate entries */}
      <div className={clsx("space-y-3", compact ? "max-h-[300px]" : "max-h-[500px]", "overflow-y-auto")}>
        <AnimatePresence>
          {active.entries.slice(0, visibleEntries).map((entry) => {
            const VoteIcon = VOTE_ICON[entry.position];
            const agentStatus: AgentStatus = "DEBATING";

            return (
              <motion.div
                key={entry.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.1 }}
                className="flex gap-3"
              >
                {/* Pixel agent avatar */}
                <div className="flex-shrink-0 pt-1">
                  <PixelAgent
                    agentId={entry.id}
                    agentType={entry.agentType}
                    status={agentStatus}
                    size={2}
                    showLabel={false}
                  />
                </div>

                {/* Speech bubble */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-semibold text-gray-300">
                      {entry.agentName}
                    </span>
                    <span
                      className={clsx(
                        "flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded border",
                        VOTE_COLOR[entry.position]
                      )}
                    >
                      <VoteIcon className="w-2.5 h-2.5" />
                      {entry.position.toUpperCase()}
                    </span>
                    <span className="text-[9px] text-gray-600">
                      {Math.round(entry.confidence * 100)}% conf
                    </span>
                  </div>
                  <motion.div
                    initial={{ scale: 0.95 }}
                    animate={{ scale: 1 }}
                    className="bg-horizon-darker border border-horizon-border rounded-lg rounded-tl-none p-2.5"
                  >
                    <p className="text-[11px] text-gray-300 leading-relaxed">
                      {entry.argument}
                    </p>
                  </motion.div>
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>

        {/* Typing indicator for active debates */}
        {active.status === "active" && visibleEntries < active.entries.length && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex items-center gap-2 pl-12"
          >
            <div className="flex gap-1">
              {[0, 1, 2].map((i) => (
                <motion.div
                  key={i}
                  animate={{ y: [0, -3, 0] }}
                  transition={{ duration: 0.5, repeat: Infinity, delay: i * 0.15 }}
                  className="w-1.5 h-1.5 rounded-full bg-gray-500"
                />
              ))}
            </div>
            <span className="text-[10px] text-gray-500">Agent thinking...</span>
          </motion.div>
        )}
      </div>
    </div>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 70202286DC40 - verify with scripts/authorship.py verify
