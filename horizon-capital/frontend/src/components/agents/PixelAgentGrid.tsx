import { useState, useEffect, useRef, useCallback } from "react";
import { motion } from "framer-motion";
import clsx from "clsx";
import PixelAgent from "./PixelAgent";
import type { AgentStatus } from "./PixelAgent";

export interface PixelAgentState {
  id: string;
  name: string;
  type: "regime" | "strategy" | "risk" | "portfolio" | "sentiment" | "debate" | "execution";
  status: AgentStatus;
  lastAction: string;
  confidence: number;
  lastHeartbeat: string;
  uptime: number;
}

// Default mock agents if store is empty
const DEFAULT_AGENTS: PixelAgentState[] = [
  { id: "regime-1", name: "Regime Detector", type: "regime", status: "ANALYZING", lastAction: "Classifying market regime", confidence: 0.87, lastHeartbeat: new Date().toISOString(), uptime: 86400 },
  { id: "strategy-1", name: "Alpha Seeker", type: "strategy", status: "ANALYZING", lastAction: "Scanning momentum signals", confidence: 0.72, lastHeartbeat: new Date().toISOString(), uptime: 86400 },
  { id: "sentiment-1", name: "Sentiment Analyzer", type: "sentiment", status: "IDLE", lastAction: "Monitoring news feeds", confidence: 0.65, lastHeartbeat: new Date().toISOString(), uptime: 86400 },
  { id: "debate-1", name: "Debate Moderator", type: "debate", status: "DEBATING", lastAction: "Bull vs Bear on NIFTY", confidence: 0.80, lastHeartbeat: new Date().toISOString(), uptime: 86400 },
  { id: "risk-1", name: "Risk Guardian", type: "risk", status: "ANALYZING", lastAction: "Calculating portfolio VaR", confidence: 0.91, lastHeartbeat: new Date().toISOString(), uptime: 86400 },
  { id: "portfolio-1", name: "Portfolio Optimizer", type: "portfolio", status: "IDLE", lastAction: "Rebalancing weights", confidence: 0.78, lastHeartbeat: new Date().toISOString(), uptime: 86400 },
  { id: "execution-1", name: "Trade Executor", type: "execution", status: "EXECUTING", lastAction: "Executing RELIANCE buy", confidence: 0.95, lastHeartbeat: new Date().toISOString(), uptime: 86400 },
];

// Workflow order: left to right
const WORKFLOW_ORDER = ["regime", "sentiment", "strategy", "debate", "risk", "portfolio", "execution"];

interface ConnectionLine {
  from: string;
  to: string;
  active: boolean;
}

// Tooltip component
function AgentTooltip({ agent }: { agent: PixelAgentState }) {
  const uptimeHrs = Math.floor(agent.uptime / 3600);
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 4 }}
      className="absolute bottom-full left-1/2 -translate-x-1/2 mb-3 z-50 pointer-events-none"
    >
      <div className="bg-horizon-dark border border-horizon-border rounded-lg p-3 shadow-2xl min-w-[180px]">
        <p className="text-xs font-bold text-white mb-1">{agent.name}</p>
        <div className="space-y-1">
          <div className="flex justify-between text-[10px]">
            <span className="text-gray-500">Status</span>
            <span className={clsx(
              agent.status === "ERROR" ? "text-accent-red" :
              agent.status === "EXECUTING" ? "text-accent-yellow" :
              agent.status === "ANALYZING" ? "text-accent-blue" : "text-gray-400"
            )}>{agent.status}</span>
          </div>
          <div className="flex justify-between text-[10px]">
            <span className="text-gray-500">Last Action</span>
            <span className="text-gray-300 text-right max-w-[120px] truncate">{agent.lastAction}</span>
          </div>
          <div className="flex justify-between text-[10px]">
            <span className="text-gray-500">Confidence</span>
            <span className="text-gray-300">{Math.round(agent.confidence * 100)}%</span>
          </div>
          <div className="flex justify-between text-[10px]">
            <span className="text-gray-500">Uptime</span>
            <span className="text-gray-300">{uptimeHrs}h</span>
          </div>
        </div>
        <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 w-2 h-2 bg-horizon-dark border-r border-b border-horizon-border rotate-45" />
      </div>
    </motion.div>
  );
}

interface PixelAgentGridProps {
  compact?: boolean;
  agents?: PixelAgentState[];
}

export default function PixelAgentGrid({ compact = false, agents: propAgents }: PixelAgentGridProps) {
  const agents = propAgents && propAgents.length > 0 ? propAgents : DEFAULT_AGENTS;
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [activeLines, setActiveLines] = useState<Set<string>>(new Set());
  const containerRef = useRef<HTMLDivElement>(null);

  // Sort agents by workflow order
  const sortedAgents = [...agents].sort(
    (a, b) => WORKFLOW_ORDER.indexOf(a.type) - WORKFLOW_ORDER.indexOf(b.type)
  );

  // Build connection lines
  const connections: ConnectionLine[] = [];
  for (let i = 0; i < sortedAgents.length - 1; i++) {
    connections.push({
      from: sortedAgents[i].id,
      to: sortedAgents[i + 1].id,
      active: sortedAgents[i].status !== "IDLE" && sortedAgents[i].status !== "ERROR",
    });
  }

  // Simulate data flow animation
  const animateFlow = useCallback(() => {
    const newActive = new Set<string>();
    connections.forEach((conn) => {
      if (conn.active && Math.random() > 0.4) {
        newActive.add(`${conn.from}-${conn.to}`);
      }
    });
    setActiveLines(newActive);
  }, [connections]);

  useEffect(() => {
    const interval = setInterval(animateFlow, 2000);
    return () => clearInterval(interval);
  }, [animateFlow]);

  const agentSize = compact ? 3 : 4;

  return (
    <div
      ref={containerRef}
      className="card overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-white">Agent Workspace</h3>
          <p className="text-[10px] text-gray-500 mt-0.5">Data Flow: Left to Right</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-accent-green animate-pulse" />
            <span className="text-[10px] text-gray-400">
              {agents.filter((a) => a.status !== "IDLE" && a.status !== "ERROR").length} Active
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-accent-red" />
            <span className="text-[10px] text-gray-400">
              {agents.filter((a) => a.status === "ERROR").length} Error
            </span>
          </div>
        </div>
      </div>

      {/* Workflow stage labels */}
      <div className={clsx(
        "grid gap-2 mb-2",
        compact ? "grid-cols-7" : "grid-cols-7"
      )}>
        {WORKFLOW_ORDER.map((type) => (
          <div key={type} className="text-center">
            <span className="text-[8px] font-bold uppercase tracking-wider text-gray-600">
              {type === "regime" ? "Regime" :
               type === "sentiment" ? "Sentiment" :
               type === "strategy" ? "Strategy" :
               type === "debate" ? "Debate" :
               type === "risk" ? "Risk" :
               type === "portfolio" ? "Portfolio" : "Execute"}
            </span>
          </div>
        ))}
      </div>

      {/* Agent grid with connection lines */}
      <div className="relative">
        {/* Connection lines (SVG overlay) */}
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none z-0"
          preserveAspectRatio="none"
        >
          {connections.map((conn, i) => {
            const isActive = activeLines.has(`${conn.from}-${conn.to}`);
            const totalSlots = sortedAgents.length;
            const fromIdx = sortedAgents.findIndex((a) => a.id === conn.from);
            const toIdx = sortedAgents.findIndex((a) => a.id === conn.to);
            const fromX = ((fromIdx + 0.5) / totalSlots) * 100;
            const toX = ((toIdx + 0.5) / totalSlots) * 100;

            return (
              <g key={i}>
                <line
                  x1={`${fromX}%`}
                  y1="50%"
                  x2={`${toX}%`}
                  y2="50%"
                  stroke={isActive ? "#3b82f6" : "#1f2937"}
                  strokeWidth={isActive ? 2 : 1}
                  strokeDasharray={isActive ? "none" : "4 4"}
                  opacity={isActive ? 0.6 : 0.3}
                />
                {isActive && (
                  <circle r="3" fill="#3b82f6" opacity="0.8">
                    <animateMotion
                      dur="1.5s"
                      repeatCount="indefinite"
                      path={`M${fromX * 3},50 L${toX * 3},50`}
                    />
                  </circle>
                )}
              </g>
            );
          })}
        </svg>

        {/* Agent characters */}
        <div className={clsx("grid gap-2 relative z-10", "grid-cols-7")}>
          {sortedAgents.map((agent) => (
            <div
              key={agent.id}
              className="flex flex-col items-center py-4 relative"
              onMouseEnter={() => setHoveredId(agent.id)}
              onMouseLeave={() => setHoveredId(null)}
            >
              {hoveredId === agent.id && <AgentTooltip agent={agent} />}
              <PixelAgent
                agentId={agent.id}
                agentType={agent.type}
                status={agent.status}
                lastAction={agent.lastAction}
                confidence={agent.confidence}
                size={agentSize}
              />
            </div>
          ))}
        </div>
      </div>

      {/* Flow arrows at bottom */}
      <div className="flex items-center justify-center gap-1 mt-3 text-gray-600">
        <span className="text-[9px]">DATA</span>
        {WORKFLOW_ORDER.map((_, i) => (
          <motion.span
            key={i}
            animate={{ opacity: [0.3, 1, 0.3] }}
            transition={{ duration: 1.5, repeat: Infinity, delay: i * 0.2 }}
            className="text-[10px]"
          >
            {i < WORKFLOW_ORDER.length - 1 ? " --> " : ""}
          </motion.span>
        ))}
        <span className="text-[9px]">TRADE</span>
      </div>
    </div>
  );
}
