// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-6BA5658DFEB6
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { Stethoscope } from "lucide-react";
import { useState } from "react";

import { useAgents, useCommand } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import {
  Badge,
  Card,
  CommandEcho,
  Dot,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  statusTone,
} from "@/components/ui";

const DEPARTMENT_LABELS: Record<string, string> = {
  front_office: "Front Office",
  middle_office: "Middle Office",
  back_office: "Back Office",
  executive: "Executive",
  unassigned: "Unassigned",
};

const DEPARTMENT_BLURB: Record<string, string> = {
  front_office: "Strategy, portfolio construction, execution, investor relations",
  middle_office: "Risk limits, compliance, operations, the debate gate",
  back_office: "Accounting, IT health, quant feature freshness",
  executive: "CIO — advisory, crisis and override authority",
};

export default function AgentsPage() {
  const { data, isLoading } = useAgents();
  const command = useCommand();
  const [echo, setEcho] = useState<{ html: string; text: string } | null>(null);

  if (isLoading) return <Loading label="Loading agents" />;
  if (!data?.live)
    return (
      <>
        <PageHeader title="Agents" />
        <ErrorNote message="No orchestrator in this process — the API is running without agents." />
      </>
    );

  const grouped = data.agents.reduce<Record<string, typeof data.agents>>((acc, agent) => {
    (acc[agent.department] ??= []).push(agent);
    return acc;
  }, {});

  const running = data.agents.filter((a) => a.status.toUpperCase() === "RUNNING").length;

  return (
    <>
      <PageHeader
        title="Agents"
        subtitle={`${running}/${data.agents.length} running · the orchestrator restarts anything that dies`}
        actions={
          <button
            className="btn"
            disabled={command.isPending}
            onClick={() =>
              command.mutate("doctor", {
                onSuccess: (r) => setEcho({ html: r.html, text: r.text }),
              })
            }
          >
            <Stethoscope className="h-3.5 w-3.5" />
            {command.isPending ? "Running" : "Run doctor"}
          </button>
        }
      />

      {echo && (
        <div className="mb-4">
          <CommandEcho html={echo.html} text={echo.text} onDismiss={() => setEcho(null)} />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {Object.entries(grouped).map(([department, agents]) => (
          <Card
            key={department}
            title={DEPARTMENT_LABELS[department] ?? department}
            subtitle={DEPARTMENT_BLURB[department]}
            bodyClassName=""
          >
            <ul className="divide-y divide-line/70">
              {agents.map((agent) => (
                <li
                  key={agent.agent_id}
                  className="flex items-center justify-between gap-3 px-4 py-2.5"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <Dot
                      tone={statusTone(agent.status)}
                      pulse={agent.status.toUpperCase() === "RUNNING"}
                    />
                    <span className="truncate font-mono text-sm text-ink">{agent.agent_id}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    {agent.retries > 0 && (
                      <span className="text-2xs text-warn">{agent.retries} restarts</span>
                    )}
                    <span className="text-xs text-soft">{timeAgo(agent.last_heartbeat)}</span>
                    <Badge tone={statusTone(agent.status)}>{agent.status}</Badge>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        ))}

        <Card title="Workers" subtitle="Supervised background loops" bodyClassName="">
          {data.workers.length === 0 ? (
            <Empty message="No supervised workers" />
          ) : (
            <ul className="divide-y divide-line/70">
              {data.workers.map((worker) => (
                <li
                  key={worker.name}
                  className="flex items-center justify-between px-4 py-2.5"
                >
                  <span className="flex items-center gap-2">
                    <Dot tone={statusTone(worker.status)} />
                    <span className="font-mono text-sm text-ink">{worker.name}</span>
                  </span>
                  <span className="flex items-center gap-3">
                    {worker.restarts > 0 && (
                      <span className="text-2xs text-warn">{worker.restarts} restarts</span>
                    )}
                    <Badge tone={statusTone(worker.status)}>{worker.status}</Badge>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 6BA5658DFEB6 - verify with scripts/authorship.py verify
