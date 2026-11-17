// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-F157CC7C062F
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import clsx from "clsx";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useDebate, useDebates, type Debate, type DebateArgument } from "@/lib/api";
import { dateTime, num } from "@/lib/format";
import { VoteBar } from "@/components/charts";
import {
  Card,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  StatusChip,
  statusTone,
  type StatusChipTone,
} from "@/components/ui";

const CHIP: Record<string, StatusChipTone> = {
  good: "ok",
  bad: "critical",
  warn: "warning",
  neutral: "neutral",
};

const decisionOf = (d: Debate) => d.final_decision ?? d.status;

function voteTone(vote: string | null | undefined): StatusChipTone {
  const v = (vote ?? "").toUpperCase();
  if (v === "FOR" || v === "APPROVE" || v === "APPROVED") return "ok";
  if (v === "AGAINST" || v === "REJECT" || v === "REJECTED") return "critical";
  if (v === "ERROR") return "warning";
  return "neutral";
}

function tally(args: DebateArgument[]) {
  const n: Record<StatusChipTone, number> = { ok: 0, critical: 0, neutral: 0, warning: 0, serious: 0 };
  for (const a of args) n[voteTone(a.vote)]++;
  return n;
}

/** Magnitude meter for a [0, 1] score; the number printed beside it carries the value. */
function Meter({ value, width }: { value: number; width: string }) {
  return (
    <span className={clsx("h-1 overflow-hidden rounded-full bg-line", width)} aria-hidden>
      <span
        className="block h-full rounded-full bg-accent"
        style={{ width: `${Math.min(Math.max(value, 0), 1) * 100}%` }}
      />
    </span>
  );
}

function OutcomesCard({ debates }: { debates: Debate[] }) {
  const count = (d: string) => debates.filter((x) => decisionOf(x).toUpperCase() === d).length;
  const approved = count("APPROVED");
  const rejected = count("REJECTED");
  const other = debates.length - approved - rejected;

  return (
    <Card
      title={`Outcomes · last ${debates.length}`}
      subtitle="Against = rejected · Abstain = inconclusive or open · For = approved"
      action={
        <div className="flex items-center gap-1.5">
          <StatusChip tone="ok" label={`${approved} approved`} />
          <StatusChip tone="critical" label={`${rejected} rejected`} />
          <StatusChip tone="neutral" label={`${other} other`} />
        </div>
      }
    >
      <VoteBar against={rejected} abstain={other} for_={approved} height={16} />
    </Card>
  );
}

function DebateDetail({ id }: { id: string }) {
  const { data, isLoading, error } = useDebate(id);

  if (isLoading) return <Loading label="Loading debate" />;
  if (error)
    return (
      <div className="p-3">
        <ErrorNote message={`Could not load debate — ${error.message}`} />
      </div>
    );
  if (!data?.session) return <Empty message="Debate not found" />;

  const session = data.session;
  const decision = decisionOf(session);
  const rounds = data.arguments.reduce<Record<number, typeof data.arguments>>(
    (acc, argument) => {
      (acc[argument.round_number] ??= []).push(argument);
      return acc;
    },
    {},
  );

  return (
    <div>
      <header className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
        <span className="text-base font-semibold text-ink">{session.symbol}</span>
        {session.proposed_action && (
          <span className="text-2xs uppercase text-ink-3">{session.proposed_action}</span>
        )}
        <StatusChip tone={CHIP[statusTone(decision)]} label={decision} />
        {session.consensus_score !== null && (
          <span className="inline-flex items-center gap-1.5 text-2xs text-ink-3">
            consensus
            <span className="nums text-ink-2">{num(session.consensus_score, 2)}</span>
            <Meter value={session.consensus_score} width="w-12" />
          </span>
        )}
        <span className="nums ml-auto text-xs text-ink-3">{dateTime(session.created_at)}</span>
      </header>

      <div className="space-y-4 p-3">
        {session.reason && (
          <p className="rounded border border-line bg-surface-2 px-3 py-2 text-sm text-ink-2">
            {session.reason}
          </p>
        )}

        {Object.keys(rounds).length === 0 ? (
          <Empty
            message="No arguments stored"
            hint="Older debates predate argument persistence; new ones keep every round."
          />
        ) : (
          Object.entries(rounds).map(([round, args]) => {
            const votes = tally(args);
            return (
              <section key={round}>
                <h3 className="mb-2 text-2xs font-semibold uppercase tracking-wide text-ink-3">
                  Round {round}
                </h3>
                <VoteBar
                  for_={votes.ok}
                  against={votes.critical}
                  abstain={votes.neutral}
                  error={votes.warning}
                />
                <div className="mt-3 space-y-2">
                  {args.map((argument, i) => (
                    <div key={i} className="rounded-md border border-line px-3 py-2.5">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-ink">{argument.role}</span>
                        <span className="font-mono text-2xs text-ink-3">{argument.agent_id}</span>
                        <StatusChip tone={voteTone(argument.vote)} label={argument.vote ?? "—"} />
                        <span className="ml-auto inline-flex items-center gap-1.5 text-2xs text-ink-3">
                          conf
                          <span className="nums text-ink-2">{num(argument.confidence, 2)}</span>
                          <Meter value={argument.confidence} width="w-10" />
                        </span>
                      </div>
                      <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-2">
                        {argument.argument}
                      </p>
                    </div>
                  ))}
                </div>
              </section>
            );
          })
        )}
      </div>
    </div>
  );
}

export default function DebatesPage() {
  const { data, isLoading, error } = useDebates();
  // ?session=<id> (from the trade timeline) opens that debate, even if it is older than the list.
  const [params] = useSearchParams();
  const [selected, setSelected] = useState<string | null>(() => params.get("session"));

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
      ) : error ? (
        <ErrorNote message={`Could not load debates — ${error.message}`} />
      ) : debates.length === 0 ? (
        <Card>
          <Empty
            message="No debates yet"
            hint="In PAPER_TRADING the gate auto-approves, so sessions appear only when an LLM debate runs."
          />
        </Card>
      ) : (
        <div className="flex flex-col gap-3">
          <OutcomesCard debates={debates} />

          <div className="grid gap-3 lg:grid-cols-[300px_1fr]">
            <Card title="Sessions" bodyClassName="">
              <ul className="max-h-[560px] divide-y divide-line overflow-y-auto">
                {debates.map((debate) => {
                  const active = current === debate.id;
                  const decision = decisionOf(debate);
                  return (
                    <li key={debate.id}>
                      <button
                        onClick={() => setSelected(debate.id)}
                        aria-current={active ? "true" : undefined}
                        className={clsx(
                          "relative w-full px-3 py-2 text-left transition-colors duration-100",
                          active ? "bg-surface-2" : "hover:bg-surface-2/60",
                        )}
                      >
                        {active && (
                          <span className="absolute inset-y-0 left-0 w-0.5 bg-accent" aria-hidden />
                        )}
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-sm font-medium text-ink">
                            {debate.symbol}
                            {debate.proposed_action && (
                              <span className="ml-1.5 text-2xs font-normal uppercase text-ink-3">
                                {debate.proposed_action}
                              </span>
                            )}
                          </span>
                          <StatusChip tone={CHIP[statusTone(decision)]} label={decision} />
                        </div>
                        <div className="mt-1 flex items-center justify-between gap-2 text-2xs text-ink-3">
                          {debate.consensus_score !== null ? (
                            <span className="inline-flex items-center gap-1.5">
                              <span className="nums text-ink-2">{num(debate.consensus_score, 2)}</span>
                              <Meter value={debate.consensus_score} width="w-12" />
                            </span>
                          ) : (
                            <span>no consensus score</span>
                          )}
                          <span className="nums">{dateTime(debate.created_at)}</span>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </Card>

            <Card bodyClassName="">
              {current ? <DebateDetail id={current} /> : <Empty message="Pick a debate" />}
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token F157CC7C062F - verify with scripts/authorship.py verify
