// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-6BA5658DFEB6
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { Stethoscope } from "lucide-react";
import { useState } from "react";

import OrgChart from "@/components/OrgChart";
import { useAgents, useCommand, type AgentInfo } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import {
  Card,
  CommandEcho,
  Dot,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  StatusChip,
  statusTone,
  type StatusChipTone,
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

const CHIP: Record<string, StatusChipTone> = {
  good: "ok",
  bad: "critical",
  warn: "warning",
  neutral: "neutral",
};

const isRunning = (status: string) => status.toUpperCase() === "RUNNING";

/** Header chip: everything up → ok, nothing up → critical, otherwise warning. */
function CountChip({ running, total }: { running: number; total: number }) {
  if (!total) return null;
  const tone = running === total ? "ok" : running === 0 ? "critical" : "warning";
  return <StatusChip tone={tone} label={`${running}/${total} running`} className="nums" />;
}

function Restarts({ count }: { count: number }) {
  if (count <= 0) return null;
  return <StatusChip tone="warning" label={`${count} restart${count === 1 ? "" : "s"}`} />;
}

export default function AgentsPage() {
  const { data, isLoading, error } = useAgents();
  const command = useCommand();
  const [echo, setEcho] = useState<{ html: string; text: string } | null>(null);

  const grouped = (data?.agents ?? []).reduce<Record<string, AgentInfo[]>>((acc, agent) => {
    (acc[agent.department] ??= []).push(agent);
    return acc;
  }, {});

  const running = data?.agents.filter((a) => isRunning(a.status)).length ?? 0;

  return (
    <>
      <PageHeader
        title="Agents"
        subtitle={
          data?.live
            ? `${running}/${data.agents.length} running · the orchestrator restarts anything that dies`
            : "The firm's agents by department"
        }
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

      <OrgChart live={data} />

      {isLoading ? (
        <Loading label="Loading agents" />
      ) : error ? (
        <ErrorNote message={`Could not load agents — ${error.message}`} />
      ) : data?.live ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {Object.entries(grouped).map(([department, agents]) => (
            <Card
              key={department}
              title={DEPARTMENT_LABELS[department] ?? department}
              subtitle={DEPARTMENT_BLURB[department]}
              action={
                <CountChip
                  running={agents.filter((a) => isRunning(a.status)).length}
                  total={agents.length}
                />
              }
              bodyClassName=""
            >
              <ul className="divide-y divide-line">
                {agents.map((agent) => (
                  <li
                    key={agent.agent_id}
                    className="flex h-8 items-center justify-between gap-3 px-3"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <Dot tone={statusTone(agent.status)} pulse={isRunning(agent.status)} />
                      <span className="truncate font-mono text-xs text-ink">{agent.agent_id}</span>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <Restarts count={agent.retries} />
                      <span className="nums text-2xs text-ink-3" title={agent.last_heartbeat}>
                        {timeAgo(agent.last_heartbeat)}
                      </span>
                      <StatusChip tone={CHIP[statusTone(agent.status)]} label={agent.status} />
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          ))}

          <Card
            title="Workers"
            subtitle="Supervised background loops"
            action={
              <CountChip
                running={data.workers.filter((w) => isRunning(w.status)).length}
                total={data.workers.length}
              />
            }
            bodyClassName=""
          >
            {data.workers.length === 0 ? (
              <Empty
                message="No supervised workers"
                hint="Workers register when the engine starts its background loops."
              />
            ) : (
              <ul className="divide-y divide-line">
                {data.workers.map((worker) => (
                  <li
                    key={worker.name}
                    className="flex h-8 items-center justify-between gap-3 px-3"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <Dot tone={statusTone(worker.status)} pulse={isRunning(worker.status)} />
                      <span className="truncate font-mono text-xs text-ink">{worker.name}</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-3">
                      <Restarts count={worker.restarts} />
                      <StatusChip tone={CHIP[statusTone(worker.status)]} label={worker.status} />
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      ) : null}
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 6BA5658DFEB6 - verify with scripts/authorship.py verify
