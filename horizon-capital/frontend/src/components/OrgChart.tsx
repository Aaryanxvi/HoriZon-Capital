import clsx from "clsx";
import { motion, useReducedMotion } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";

import type { AgentInfo, AgentsResponse } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { describeEvent, useLiveStore, type LiveEvent } from "@/lib/live";
import { channelMatches, useOrg, type OrgAgent, type OrgLink } from "@/lib/org-api";
import { Card, ErrorNote, Loading, StatusChip, statusTone, type StatusChipTone } from "@/components/ui";

// The firm as a graph: departments are bands, links are bus subscriptions
// (derived server-side from what each agent emits and subscribes to). A live
// message pulses along every link it travels and lights up its sender.

const W = 960;
const GUTTER = 112; // band labels
const BAND_H = 112;
const TOP = 44;
const NODE_W = 132;
const NODE_H = 34;
const PULSE_MS = 850;
const MAX_PULSES = 8; // ponytail: drop pulses past the cap rather than queue them

const CHIP: Record<string, StatusChipTone> = { good: "ok", bad: "critical", warn: "warning", neutral: "neutral" };
const DOT_FILL: Record<string, string> = { good: "fill-ok", bad: "fill-crit", warn: "fill-warn", neutral: "fill-ink-3" };

type Pt = { x: number; y: number };
interface Edge extends OrgLink {
  key: string;
  a: Pt; // trimmed start
  c: Pt; // quadratic control point
  b: Pt; // trimmed end
}

const linkKey = (l: OrgLink) => `${l.from}>${l.to}`;

/** Where the ray from a node's centre toward `p` leaves its box (plus a small gap). */
function exitPoint(center: Pt, p: Pt, gap: number): Pt {
  const dx = p.x - center.x;
  const dy = p.y - center.y;
  const t = Math.min((NODE_W / 2 + gap) / Math.abs(dx || 1e-6), (NODE_H / 2 + gap) / Math.abs(dy || 1e-6));
  return { x: center.x + dx * t, y: center.y + dy * t };
}

function bezier(e: Edge, t: number): Pt {
  const u = 1 - t;
  return {
    x: u * u * e.a.x + 2 * u * t * e.c.x + t * t * e.b.x,
    y: u * u * e.a.y + 2 * u * t * e.c.y + t * t * e.b.y,
  };
}

function useLayout(agents: OrgAgent[], departments: string[], links: OrgLink[]) {
  return useMemo(() => {
    const pos: Record<string, Pt> = {};
    const gaps: number[][] = []; // per band: x of the free space between/around nodes
    departments.forEach((dept, row) => {
      const inDept = agents.filter((a) => a.department === dept);
      const step = (W - GUTTER - 8) / Math.max(inDept.length, 1);
      const xs = inDept.map((_, i) => GUTTER + step * (i + 0.5));
      inDept.forEach((a, i) => {
        pos[a.id] = { x: xs[i], y: TOP + row * BAND_H };
      });
      gaps[row] = xs.length
        ? [xs[0] - NODE_W / 2 - 12, ...xs.slice(1).map((x, i) => (x + xs[i]) / 2), xs[xs.length - 1] + NODE_W / 2 + 12]
        : [];
    });
    const rowOf = (y: number) => Math.round((y - TOP) / BAND_H);
    const edges: Edge[] = links
      .filter((l) => pos[l.from] && pos[l.to])
      .map((l) => {
        const p = pos[l.from];
        const q = pos[l.to];
        const dx = q.x - p.x;
        const dy = q.y - p.y;
        const len = Math.hypot(dx, dy) || 1;
        // Bow to the left of travel, so A→B and B→A take mirrored arcs.
        const bow = Math.min(36, 14 + len * 0.08);
        let c = { x: (p.x + q.x) / 2 + (dy / len) * bow, y: (p.y + q.y) / 2 - (dx / len) * bow };
        // A link that skips a band threads the nearest gap in it instead of
        // running behind a node it has nothing to do with: C = 2M - (P+Q)/2
        // puts the curve's midpoint exactly on the gap M.
        const between = gaps[(rowOf(p.y) + rowOf(q.y)) / 2];
        if (Math.abs(rowOf(p.y) - rowOf(q.y)) === 2 && between?.length) {
          const mid = (p.x + q.x) / 2;
          const gx = between.reduce((best, g) =>
            Math.abs(g - mid) < Math.abs(best - mid) ? g : best,
          );
          c = { x: 2 * gx - mid, y: (p.y + q.y) / 2 };
        }
        return { ...l, key: linkKey(l), a: exitPoint(p, c, 2), c, b: exitPoint(q, c, 5) };
      });
    const height = TOP + (departments.length - 1) * BAND_H + TOP;
    return { pos, edges, height };
  }, [agents, departments, links]);
}

export default function OrgChart({ live }: { live: AgentsResponse | undefined }) {
  const { data: org, isLoading, error } = useOrg();
  const reduceMotion = useReducedMotion();
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [hot, setHot] = useState<Record<string, number>>({}); // node id / link key → nonce
  const [pulses, setPulses] = useState<{ id: number; edge: Edge }[]>([]);
  const nonce = useRef(0);

  const agents = org?.agents ?? [];
  const departments = useMemo(() => (org?.departments ?? []).map((d) => d.id), [org]);
  const { pos, edges, height } = useLayout(agents, departments, org?.links ?? []);
  const running = !!live?.live;
  const status = useMemo(
    () => Object.fromEntries((live?.agents ?? []).map((a) => [a.agent_id, a])) as Record<string, AgentInfo>,
    [live],
  );

  // One subscription to the bus tail; only the newest event matters per update.
  useEffect(() => {
    const flash = (keys: string[]) => {
      const n = ++nonce.current;
      setHot((h) => ({ ...h, ...Object.fromEntries(keys.map((k) => [k, n])) }));
      setTimeout(
        () => setHot((h) => Object.fromEntries(Object.entries(h).filter(([, v]) => v !== n))),
        PULSE_MS + 150,
      );
    };
    return useLiveStore.subscribe((state, prev) => {
      const event: LiveEvent | undefined = state.events[0];
      if (!event || event === prev.events[0] || !pos[event.sender]) return;
      const hit = edges.filter(
        (e) => e.from === event.sender && e.channels.some((g) => channelMatches(event.channel, g)),
      );
      flash([event.sender, ...hit.map((e) => e.key)]);
      if (reduceMotion || !hit.length) return;
      setPulses((ps) => {
        const room = MAX_PULSES - ps.length;
        if (room <= 0) return ps;
        return [...ps, ...hit.slice(0, room).map((edge) => ({ id: ++nonce.current, edge }))];
      });
    });
  }, [edges, pos, reduceMotion]);

  if (isLoading) return <Loading label="Loading org chart" />;
  if (error || !org) return <ErrorNote message={`Could not load the org chart — ${error?.message ?? "no data"}`} />;

  const focus = selected ?? hovered;
  const byId = Object.fromEntries(agents.map((a) => [a.id, a]));
  const toneOf = (a: OrgAgent) => (running && status[a.id] ? statusTone(status[a.id].status) : "neutral");

  return (
    <Card
      title="Org chart"
      subtitle="Who talks to whom on the bus — each link is a channel one agent publishes and another subscribes to"
      className="mb-4"
      bodyClassName=""
    >
      {!running && (
        <p className="border-b border-line bg-surface-2 px-3 py-1.5 text-xs text-ink-2">
          Engine is off — the firm is drawn from its agent definitions. Links pulse as agents
          publish once the engine runs.
        </p>
      )}
      <div className="grid lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="overflow-x-auto p-2">
          <svg
            viewBox={`0 0 ${W} ${height}`}
            className="h-auto w-full min-w-[720px] select-none"
            role="group"
            aria-label="Agent org chart"
          >
            <defs>
              <marker id="org-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
                <path d="M0,0 L8,4 L0,8 z" className="fill-line-strong" />
              </marker>
              <marker id="org-arrow-hot" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
                <path d="M0,0 L8,4 L0,8 z" className="fill-accent" />
              </marker>
            </defs>

            {org.departments.map((d, row) => (
              <g key={d.id}>
                {row > 0 && (
                  <line x1={8} x2={W - 8} y1={TOP + (row - 0.5) * BAND_H} y2={TOP + (row - 0.5) * BAND_H} className="stroke-line" />
                )}
                <text x={12} y={TOP + row * BAND_H + 4} className="fill-ink-3 text-[11px] font-medium uppercase tracking-wide">
                  {d.label}
                </text>
              </g>
            ))}

            {edges.map((e) => {
              const lit = !!hot[e.key] || (focus !== null && (e.from === focus || e.to === focus));
              const dim = focus !== null && !lit;
              const d = `M${e.a.x},${e.a.y} Q${e.c.x},${e.c.y} ${e.b.x},${e.b.y}`;
              return (
                <g key={e.key}>
                  <path
                    d={d}
                    fill="none"
                    markerEnd={`url(#${lit ? "org-arrow-hot" : "org-arrow"})`}
                    className={clsx(
                      "transition-[stroke,opacity] duration-200",
                      lit ? "stroke-accent" : "stroke-line-strong",
                      dim && "opacity-25",
                    )}
                    strokeWidth={lit ? 1.5 : 1}
                  />
                  {/* Wide invisible stroke: a 1px line is too thin to hover. */}
                  <path d={d} fill="none" stroke="transparent" strokeWidth={10}>
                    <title>{`${byId[e.from]?.label} → ${byId[e.to]?.label}\n${e.channels.join("\n")}`}</title>
                  </path>
                </g>
              );
            })}

            {pulses.map(({ id, edge }) => {
              const pts = Array.from({ length: 13 }, (_, i) => bezier(edge, i / 12));
              return (
                <motion.circle
                  key={id}
                  r={3.5}
                  className="fill-accent"
                  initial={{ cx: pts[0].x, cy: pts[0].y, opacity: 0 }}
                  animate={{ cx: pts.map((p) => p.x), cy: pts.map((p) => p.y), opacity: [0, 1, 1, 0] }}
                  transition={{ duration: PULSE_MS / 1000, ease: "easeInOut" }}
                  onAnimationComplete={() => setPulses((ps) => ps.filter((p) => p.id !== id))}
                />
              );
            })}

            {agents.map((a) => {
              const p = pos[a.id];
              if (!p) return null;
              const isSel = selected === a.id;
              const lit = !!hot[a.id];
              const off = !a.enabled || (running && !status[a.id]);
              return (
                <g
                  key={a.id}
                  transform={`translate(${p.x - NODE_W / 2},${p.y - NODE_H / 2})`}
                  role="button"
                  tabIndex={0}
                  aria-pressed={isSel}
                  aria-label={`${a.label} agent`}
                  className="cursor-pointer outline-none [&:focus-visible>rect]:stroke-accent"
                  onClick={() => setSelected(isSel ? null : a.id)}
                  onKeyDown={(ev) => {
                    if (ev.key === "Enter" || ev.key === " ") {
                      ev.preventDefault();
                      setSelected(isSel ? null : a.id);
                    }
                  }}
                  onMouseEnter={() => setHovered(a.id)}
                  onMouseLeave={() => setHovered(null)}
                >
                  <title>{a.role}</title>
                  <rect
                    width={NODE_W}
                    height={NODE_H}
                    rx={6}
                    className={clsx(
                      "transition-[stroke,fill] duration-200",
                      isSel ? "fill-surface-2" : "fill-surface",
                      isSel || lit ? "stroke-accent" : "stroke-line-strong",
                    )}
                    strokeWidth={isSel || lit ? 2 : 1}
                  />
                  <circle cx={14} cy={NODE_H / 2} r={3.5} className={DOT_FILL[toneOf(a)]} />
                  <text
                    x={24}
                    y={NODE_H / 2 + 4}
                    className={clsx("text-[12px] font-medium", off ? "fill-ink-3" : "fill-ink")}
                  >
                    {a.label}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>

        <AgentDetail
          agent={selected ? byId[selected] : undefined}
          info={selected ? status[selected] : undefined}
          running={running}
          edges={edges}
          byId={byId}
        />
      </div>
    </Card>
  );
}

function AgentDetail({
  agent,
  info,
  running,
  edges,
  byId,
}: {
  agent: OrgAgent | undefined;
  info: AgentInfo | undefined;
  running: boolean;
  edges: Edge[];
  byId: Record<string, OrgAgent>;
}) {
  const events = useLiveStore((s) => s.events);
  const recent = useMemo(
    () => (agent ? events.filter((e) => e.sender === agent.id).slice(0, 6) : []),
    [events, agent],
  );

  if (!agent)
    return (
      <aside className="border-t border-line p-3 text-xs text-ink-3 lg:border-l lg:border-t-0">
        Select an agent to see its status, the channels it talks on and its latest messages.
      </aside>
    );

  const label = !running ? "Engine off" : (info?.status ?? (agent.enabled ? "Not started" : "Disabled"));
  const out = edges.filter((e) => e.from === agent.id);
  const inc = edges.filter((e) => e.to === agent.id);

  return (
    <aside className="space-y-3 border-t border-line p-3 lg:border-l lg:border-t-0">
      <div>
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-ink">{agent.label}</h3>
          <StatusChip tone={running && info ? CHIP[statusTone(info.status)] : "neutral"} label={label} />
        </div>
        <p className="font-mono text-2xs text-ink-3">{agent.id}</p>
        <p className="mt-1 text-xs text-ink-2">{agent.role}</p>
        {agent.note && <p className="mt-1 text-xs text-ink-3">{agent.note}</p>}
        {info && (
          <p className="nums mt-1 text-2xs text-ink-3">
            heartbeat {timeAgo(info.last_heartbeat)}
            {info.retries > 0 && ` · ${info.retries} restart${info.retries === 1 ? "" : "s"}`}
          </p>
        )}
      </div>

      <LinkList title="Sends to" edges={out} name={(e) => byId[e.to]?.label ?? e.to} />
      <LinkList title="Listens to" edges={inc} name={(e) => byId[e.from]?.label ?? e.from} />

      <div>
        <h4 className="text-2xs font-medium uppercase tracking-wide text-ink-3">Recent messages</h4>
        {recent.length === 0 ? (
          <p className="mt-1 text-xs text-ink-3">
            {running ? "Nothing from this agent since the window opened." : "Appears once the engine runs."}
          </p>
        ) : (
          <ul className="mt-1 space-y-1">
            {recent.map((e, i) => (
              <li key={`${e.timestamp}-${i}`} className="text-xs text-ink-2">
                <span className="nums mr-1.5 text-2xs text-ink-3">{timeAgo(e.timestamp)}</span>
                {describeEvent(e)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

function LinkList({ title, edges, name }: { title: string; edges: Edge[]; name: (e: Edge) => string }) {
  if (!edges.length) return null;
  return (
    <div>
      <h4 className="text-2xs font-medium uppercase tracking-wide text-ink-3">{title}</h4>
      <ul className="mt-1 space-y-1">
        {edges.map((e) => (
          <li key={e.key} className="text-xs text-ink">
            {name(e)}
            <span className="block truncate font-mono text-2xs text-ink-3" title={e.channels.join(", ")}>
              {e.channels.map((c) => c.replace(/^horizon\./, "")).join(", ")}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
