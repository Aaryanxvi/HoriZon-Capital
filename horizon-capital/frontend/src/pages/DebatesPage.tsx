// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-F157CC7C062F
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import clsx from "clsx";
import { useState } from "react";

import { useDebate, useDebates } from "@/lib/api";
import { dateTime, num } from "@/lib/format";
import {
  Badge,
  Card,
  Empty,
  Loading,
  PageHeader,
  statusTone,
} from "@/components/ui";

function voteTone(vote: string | null | undefined): string {
  const v = (vote ?? "").toUpperCase();
  if (v === "FOR" || v === "APPROVE" || v === "APPROVED") return "good";
  if (v === "AGAINST" || v === "REJECT" || v === "REJECTED") return "bad";
  if (v === "ERROR") return "bad";
  return "neutral";
}

function DebateDetail({ id }: { id: string }) {
  const { data, isLoading } = useDebate(id);

  if (isLoading) return <Loading label="Loading debate" />;
  if (!data?.session) return <Empty message="Debate not found" />;

  const rounds = data.arguments.reduce<Record<number, typeof data.arguments>>(
    (acc, argument) => {
      (acc[argument.round_number] ??= []).push(argument);
      return acc;
    },
    {},
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-base font-semibold text-ink">{data.session.symbol}</span>
        <Badge tone={statusTone(data.session.final_decision ?? data.session.status)}>
          {data.session.final_decision ?? data.session.status}
        </Badge>
        {data.session.consensus_score !== null && (
          <span className="nums text-xs text-soft">
            consensus {num(data.session.consensus_score, 2)}
          </span>
        )}
        <span className="text-xs text-faint">{dateTime(data.session.created_at)}</span>
      </div>

      {data.session.reason && (
        <p className="rounded-lg border border-line bg-raised px-3 py-2 text-sm text-soft">
          {data.session.reason}
        </p>
      )}

      {Object.keys(rounds).length === 0 ? (
        <Empty
          message="No arguments stored"
          hint="Older debates predate argument persistence; new ones keep every round."
        />
      ) : (
        Object.entries(rounds).map(([round, args]) => (
          <div key={round}>
            <h3 className="mb-2 text-2xs font-semibold uppercase tracking-wider text-faint">
              Round {round}
            </h3>
            <div className="space-y-2">
              {args.map((argument, i) => (
                <div key={i} className="rounded-lg border border-line px-3 py-2.5">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-ink">{argument.role}</span>
                    <span className="font-mono text-2xs text-faint">{argument.agent_id}</span>
                    <Badge tone={voteTone(argument.vote)}>{argument.vote ?? "—"}</Badge>
                    <span className="nums text-2xs text-soft">
                      conf {num(argument.confidence, 2)}
                    </span>
                  </div>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-soft">
                    {argument.argument}
                  </p>
                </div>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}

export default function DebatesPage() {
  const { data, isLoading } = useDebates();
  const [selected, setSelected] = useState<string | null>(null);

  const debates = data?.debates ?? [];
  const current = selected ?? debates[0]?.id ?? null;

  return (
    <>
      <PageHeader
        title="Debates"
        subtitle="Multi-model consensus on proposed trades — binding only in FULLY_AUTONOMOUS mode"
      />

      {isLoading ? (
        <Loading />
      ) : debates.length === 0 ? (
        <Card>
          <Empty
            message="No debates yet"
            hint="In PAPER_TRADING the gate auto-approves, so sessions appear only when an LLM debate runs."
          />
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
          <Card title="Sessions" bodyClassName="">
            <ul className="max-h-[560px] divide-y divide-line/70 overflow-y-auto">
              {debates.map((debate) => (
                <li key={debate.id}>
                  <button
                    onClick={() => setSelected(debate.id)}
                    className={clsx(
                      "w-full px-4 py-2.5 text-left transition",
                      current === debate.id ? "bg-raised" : "hover:bg-raised/60",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium text-ink">
                        {debate.symbol}
                      </span>
                      <Badge tone={statusTone(debate.final_decision ?? debate.status)}>
                        {debate.final_decision ?? debate.status}
                      </Badge>
                    </div>
                    <div className="mt-0.5 text-2xs text-faint">
                      {debate.proposed_action ?? "—"} · {dateTime(debate.created_at)}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </Card>

          <Card>{current ? <DebateDetail id={current} /> : <Empty message="Pick a debate" />}</Card>
        </div>
      )}
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token F157CC7C062F - verify with scripts/authorship.py verify
