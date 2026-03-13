import { useMemo } from "react";
import { motion } from "framer-motion";
import clsx from "clsx";
export type AgentStatus = "IDLE" | "ANALYZING" | "DEBATING" | "EXECUTING" | "ERROR";

// ---------------------------------------------------------------------------
// Pixel art patterns (12x12 grid). 1 = body, 2 = eye, 3 = accent, 0 = empty
// ---------------------------------------------------------------------------

const ROBOT_PATTERN = [
  [0, 0, 0, 0, 3, 3, 3, 3, 0, 0, 0, 0],
  [0, 0, 0, 3, 3, 3, 3, 3, 3, 0, 0, 0],
  [0, 0, 3, 1, 1, 1, 1, 1, 1, 3, 0, 0],
  [0, 0, 1, 1, 2, 1, 1, 2, 1, 1, 0, 0],
  [0, 0, 1, 1, 2, 1, 1, 2, 1, 1, 0, 0],
  [0, 0, 1, 1, 1, 3, 3, 1, 1, 1, 0, 0],
  [0, 0, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0],
  [0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 3, 0],
  [0, 3, 1, 1, 3, 1, 1, 3, 1, 1, 3, 0],
  [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0],
  [0, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 0],
  [0, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 0],
];

const AGENT_COLORS: Record<string, { body: string; accent: string; eye: string; glow: string }> = {
  regime:    { body: "#7c3aed", accent: "#a78bfa", eye: "#e9d5ff", glow: "#8b5cf6" },
  strategy:  { body: "#2563eb", accent: "#60a5fa", eye: "#dbeafe", glow: "#3b82f6" },
  risk:      { body: "#dc2626", accent: "#f87171", eye: "#fecaca", glow: "#ef4444" },
  portfolio: { body: "#059669", accent: "#34d399", eye: "#d1fae5", glow: "#10b981" },
  sentiment: { body: "#d97706", accent: "#fbbf24", eye: "#fef3c7", glow: "#f59e0b" },
  debate:    { body: "#0891b2", accent: "#22d3ee", eye: "#cffafe", glow: "#06b6d4" },
  execution: { body: "#ea580c", accent: "#fb923c", eye: "#ffedd5", glow: "#f97316" },
};

const STATUS_LABELS: Record<AgentStatus, string> = {
  IDLE: "Idle",
  ANALYZING: "Analyzing",
  DEBATING: "Debating",
  EXECUTING: "Executing",
  ERROR: "Error",
};

interface PixelAgentProps {
  agentId: string;
  agentType: string;
  status: AgentStatus;
  lastAction?: string;
  confidence?: number;
  size?: number;
  showLabel?: boolean;
  onClick?: () => void;
}

export default function PixelAgent({
  agentType,
  status,
  lastAction,
  confidence,
  size = 4,
  showLabel = true,
  onClick,
}: PixelAgentProps) {
  const colors = AGENT_COLORS[agentType] || AGENT_COLORS.strategy;

  const pixels = useMemo(() => {
    const result: { x: number; y: number; color: string }[] = [];
    for (let row = 0; row < ROBOT_PATTERN.length; row++) {
      for (let col = 0; col < ROBOT_PATTERN[row].length; col++) {
        const val = ROBOT_PATTERN[row][col];
        if (val === 0) continue;
        let color = colors.body;
        if (val === 2) color = colors.eye;
        if (val === 3) color = colors.accent;
        result.push({ x: col, y: row, color });
      }
    }
    return result;
  }, [colors]);

  // Animation variants per status
  const containerVariants = {
    IDLE: {
      y: [0, -3, 0],
      opacity: 0.7,
      transition: { y: { duration: 2.5, repeat: Infinity, ease: "easeInOut" }, opacity: { duration: 0.3 } },
    },
    ANALYZING: {
      y: [0, -2, 0],
      opacity: 1,
      scale: [1, 1.03, 1],
      transition: { y: { duration: 1.2, repeat: Infinity }, scale: { duration: 1.2, repeat: Infinity } },
    },
    DEBATING: {
      y: [0, -6, 0],
      opacity: 1,
      transition: { y: { duration: 0.5, repeat: Infinity, ease: "easeOut" } },
    },
    EXECUTING: {
      opacity: [1, 0.6, 1],
      scale: [1, 1.05, 1],
      transition: { opacity: { duration: 0.15, repeat: Infinity }, scale: { duration: 0.3, repeat: Infinity } },
    },
    ERROR: {
      x: [-2, 2, -2, 2, 0],
      opacity: [1, 0.5, 1],
      transition: { x: { duration: 0.4, repeat: Infinity }, opacity: { duration: 0.6, repeat: Infinity } },
    },
  };

  const glowVariants = {
    IDLE: { opacity: 0, scale: 1 },
    ANALYZING: {
      opacity: [0.3, 0.6, 0.3],
      scale: [1, 1.2, 1],
      transition: { duration: 1.5, repeat: Infinity },
    },
    DEBATING: {
      opacity: [0.2, 0.5, 0.2],
      scale: [1, 1.15, 1],
      transition: { duration: 0.8, repeat: Infinity },
    },
    EXECUTING: {
      opacity: [0.4, 0.8, 0.4],
      scale: [1, 1.3, 1],
      transition: { duration: 0.3, repeat: Infinity },
    },
    ERROR: {
      opacity: [0.5, 0.8, 0.5],
      scale: [1, 1.2, 1],
      transition: { duration: 0.5, repeat: Infinity },
    },
  };

  const gridW = 12 * size;
  const gridH = 12 * size;

  return (
    <div
      className={clsx(
        "flex flex-col items-center gap-1 cursor-pointer select-none",
        onClick && "hover:scale-105 transition-transform"
      )}
      onClick={onClick}
    >
      {/* Thinking dots for ANALYZING */}
      {status === "ANALYZING" && (
        <div className="flex gap-1 h-4">
          {[0, 1, 2].map((i) => (
            <motion.div
              key={i}
              animate={{ y: [0, -4, 0], opacity: [0.4, 1, 0.4] }}
              transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.15 }}
              className="w-1.5 h-1.5 rounded-full"
              style={{ backgroundColor: colors.accent }}
            />
          ))}
        </div>
      )}

      {/* Speech bubble for DEBATING */}
      {status === "DEBATING" && (
        <motion.div
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: [1, 1.05, 1] }}
          transition={{ scale: { duration: 0.8, repeat: Infinity } }}
          className="relative bg-horizon-card border border-horizon-border rounded-lg px-2 py-1 mb-1"
        >
          <span className="text-[9px] text-gray-300 whitespace-nowrap">
            {lastAction?.slice(0, 20) || "Debating..."}
          </span>
          <div
            className="absolute -bottom-1 left-1/2 -translate-x-1/2 w-2 h-2 bg-horizon-card border-r border-b border-horizon-border rotate-45"
          />
        </motion.div>
      )}

      {/* Action lines for EXECUTING */}
      {status === "EXECUTING" && (
        <div className="absolute -inset-2 pointer-events-none">
          {[0, 1, 2, 3].map((i) => (
            <motion.div
              key={i}
              className="absolute w-0.5 bg-current rounded-full"
              style={{
                color: colors.accent,
                height: 6,
                left: `${20 + i * 20}%`,
                top: -4,
              }}
              animate={{ opacity: [0, 1, 0], y: [0, -6, -12] }}
              transition={{ duration: 0.4, repeat: Infinity, delay: i * 0.1 }}
            />
          ))}
        </div>
      )}

      {/* Agent pixel body */}
      <div className="relative">
        {/* Glow effect */}
        <motion.div
          className="absolute rounded-full blur-xl -inset-3"
          style={{ backgroundColor: status === "ERROR" ? "#ef4444" : colors.glow }}
          variants={glowVariants}
          animate={status}
        />

        {/* Pixel grid */}
        <motion.div
          className="relative"
          style={{ width: gridW, height: gridH }}
          variants={containerVariants}
          animate={status}
        >
          {pixels.map(({ x, y, color }, i) => (
            <div
              key={i}
              className="absolute"
              style={{
                left: x * size,
                top: y * size,
                width: size,
                height: size,
                backgroundColor: status === "ERROR" && Math.random() > 0.5 ? "#ef4444" : color,
              }}
            />
          ))}
        </motion.div>
      </div>

      {/* Label */}
      {showLabel && (
        <div className="flex flex-col items-center mt-1">
          <span className="text-[10px] font-bold text-gray-300 capitalize">
            {agentType}
          </span>
          <span
            className={clsx(
              "text-[9px] font-medium",
              status === "IDLE" && "text-gray-500",
              status === "ANALYZING" && "text-accent-blue",
              status === "DEBATING" && "text-cyan-400",
              status === "EXECUTING" && "text-accent-yellow",
              status === "ERROR" && "text-accent-red"
            )}
          >
            {STATUS_LABELS[status]}
          </span>
          {confidence !== undefined && (
            <div className="flex items-center gap-1 mt-0.5">
              <div className="w-8 h-1 bg-horizon-border rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${confidence * 100}%`,
                    backgroundColor: colors.glow,
                  }}
                />
              </div>
              <span className="text-[8px] text-gray-500">
                {Math.round(confidence * 100)}%
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
