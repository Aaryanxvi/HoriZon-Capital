import { useEffect, useCallback } from "react";
import AgentCard from "@/components/agents/AgentCard";
import DebateViewer from "@/components/agents/DebateViewer";
import type { PixelAgentState } from "@/components/agents/PixelAgentGrid";
import type { AgentStatus } from "@/components/agents/PixelAgent";
import { useAgentStore, initAgentPolling } from "@/store";
import { pauseAgent, resumeAgent } from "@/api/client";
import type { Agent } from "@/api/client";

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

export default function AgentsPage() {
  const agents = useAgentStore((s) => s.agents);
  const updateAgent = useAgentStore((s) => s.updateAgent);

  useEffect(() => {
    const cleanup = initAgentPolling();
    return cleanup;
  }, []);

  const handlePause = useCallback(
    async (id: string) => {
      try {
        await pauseAgent(id);
        updateAgent(id, { status: "paused", pixelState: "IDLE" });
      } catch {
        /* toast error in real app */
      }
    },
    [updateAgent]
  );

  const handleResume = useCallback(
    async (id: string) => {
      try {
        await resumeAgent(id);
        updateAgent(id, { status: "active", pixelState: "ANALYZING" });
      } catch {
        /* toast error in real app */
      }
    },
    [updateAgent]
  );

  const pixelAgents = agents.map(toPixelAgent);

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">Agents</h1>

      {/* Agent cards grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        {pixelAgents.length > 0
          ? pixelAgents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                onPause={handlePause}
                onResume={handleResume}
              />
            ))
          : (
            <p className="text-gray-400 col-span-2">
              No agents registered. Start the backend to see live agent data.
            </p>
          )}
      </div>

      {/* Debate viewer */}
      <DebateViewer />
    </div>
  );
}
