import { useEffect } from "react";
import PixelAgentGrid from "@/components/agents/PixelAgentGrid";
import type { PixelAgentState } from "@/components/agents/PixelAgentGrid";
import type { AgentStatus } from "@/components/agents/PixelAgent";
import { useAgentStore, initAgentPolling } from "@/store";
import type { Agent } from "@/api/client";

// Map backend agent type to pixel grid type
const TYPE_MAP: Record<string, PixelAgentState["type"]> = {
  "regime-agent": "regime",
  regime_agent: "regime",
  "strategy-agent": "strategy",
  strategy_agent: "strategy",
  "sentiment-agent": "sentiment",
  sentiment_agent: "sentiment",
  "risk-manager": "risk",
  risk_manager: "risk",
  "portfolio-manager": "portfolio",
  portfolio_manager: "portfolio",
  "debate-moderator": "debate",
  debate_moderator: "debate",
  "execution-agent": "execution",
  execution_agent: "execution",
};

function toPixelAgent(agent: Agent): PixelAgentState {
  return {
    id: agent.id,
    name: agent.name,
    type: TYPE_MAP[agent.type] ?? "strategy",
    status: (agent.pixelState ?? "IDLE") as AgentStatus,
    lastAction: agent.description || "Waiting...",
    confidence: agent.accuracy_30d || 0.5,
    lastHeartbeat: agent.lastHeartbeat ?? new Date().toISOString(),
    uptime: 86400,
  };
}

export default function DashboardPage() {
  const agents = useAgentStore((s) => s.agents);

  useEffect(() => {
    const cleanup = initAgentPolling();
    return cleanup;
  }, []);

  const pixelAgents: PixelAgentState[] = agents.length > 0
    ? agents.map(toPixelAgent)
    : [];

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">Dashboard</h1>
      <PixelAgentGrid agents={pixelAgents} />
    </div>
  );
}
