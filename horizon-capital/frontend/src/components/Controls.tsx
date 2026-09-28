// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-16D54186B69E
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import clsx from "clsx";
import {
  ChevronDown,
  OctagonAlert,
  Play,
  Power,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  useEngineControl,
  useHalt,
  useOverview,
  useUpdateSettings,
} from "@/lib/api";
import { Dot } from "@/components/ui";

const MODES = [
  { key: "PAPER_TRADING", label: "Paper trading", hint: "Fills immediately, debate auto-approves" },
  { key: "HUMAN_APPROVAL", label: "Human approval", hint: "Every order waits for you" },
  { key: "FULLY_AUTONOMOUS", label: "Fully autonomous", hint: "LLM debate gate is binding" },
];

function useOutsideClose(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);
  return ref;
}

/** Trading mode, switchable in two clicks — it writes .env and the live Settings. */
export function ModeSwitcher() {
  const { data } = useOverview();
  const update = useUpdateSettings();
  const [open, setOpen] = useState(false);
  const ref = useOutsideClose(() => setOpen(false));

  const current = MODES.find((m) => m.key === data?.system_mode);

  return (
    <div className="relative no-drag" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-2xs font-medium text-soft transition hover:bg-raised hover:text-ink"
        title="Trading mode"
      >
        {current?.label ?? data?.system_mode ?? "mode"}
        <ChevronDown className="h-3 w-3" />
      </button>

      {open && (
        <div className="absolute right-0 top-8 z-50 w-64 overflow-hidden rounded-xl border border-line bg-surface shadow-lg">
          {MODES.map((mode) => (
            <button
              key={mode.key}
              disabled={update.isPending}
              onClick={() => {
                update.mutate({ SYSTEM_MODE: mode.key });
                setOpen(false);
              }}
              className={clsx(
                "block w-full px-3 py-2.5 text-left transition hover:bg-raised",
                data?.system_mode === mode.key && "bg-clay/5",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-ink">{mode.label}</span>
                {data?.system_mode === mode.key && <Dot tone="good" />}
              </div>
              <div className="text-2xs text-soft">{mode.hint}</div>
            </button>
          ))}
          <p className="border-t border-line px-3 py-2 text-2xs text-faint">
            Applies to new signals immediately and is saved to .env.
          </p>
        </div>
      )}
    </div>
  );
}

/** The stop button. Halting is one click; resuming asks first. */
export function HaltButton() {
  const { data } = useOverview();
  const halt = useHalt();
  const halted = Boolean(data?.halted || data?.kill_switch);
  const [confirmResume, setConfirmResume] = useState(false);
  const ref = useOutsideClose(() => setConfirmResume(false));

  if (halted) {
    return (
      <div className="relative no-drag" ref={ref}>
        <button
          onClick={() => setConfirmResume((c) => !c)}
          disabled={halt.isPending}
          className="flex items-center gap-1.5 rounded-md bg-down px-2.5 py-1 text-2xs font-semibold uppercase tracking-wide text-white transition hover:bg-down/90"
          title={data?.halt_reason ?? "Trading halted"}
        >
          <OctagonAlert className="h-3.5 w-3.5" />
          Halted
        </button>

        {confirmResume && (
          <div className="absolute right-0 top-8 z-50 w-72 rounded-xl border border-line bg-surface p-3 shadow-lg">
            <p className="text-sm font-medium text-ink">Resume trading?</p>
            <p className="mt-1 text-xs text-soft">
              {data?.halt_reason
                ? `Halted because: ${data.halt_reason}`
                : "Trading is halted; the execution agent is rejecting new orders."}
            </p>
            <p className="mt-1 text-xs text-soft">
              Resuming clears the kill switch. If a drawdown limit caused it, the risk agent
              can trip it again within seconds.
            </p>
            <div className="mt-3 flex justify-end gap-2">
              <button className="btn" onClick={() => setConfirmResume(false)}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                disabled={halt.isPending}
                onClick={() => {
                  halt.mutate({ halted: false });
                  setConfirmResume(false);
                }}
              >
                <ShieldCheck className="h-3.5 w-3.5" /> Resume
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <button
      onClick={() => halt.mutate({ halted: true, reason: "Halted from the desktop app" })}
      disabled={halt.isPending}
      className="no-drag flex items-center gap-1.5 rounded-md border border-down/30 px-2.5 py-1 text-2xs font-semibold uppercase tracking-wide text-down transition hover:bg-down hover:text-white"
      title="Stop all new orders immediately"
    >
      <OctagonAlert className="h-3.5 w-3.5" />
      Halt
    </button>
  );
}

/** Start/stop the agents without closing the window. */
export function EngineButton() {
  const { data } = useOverview();
  const engine = useEngineControl();
  const running = Boolean(data?.agents_live && data.agents_running > 0);
  const [open, setOpen] = useState(false);
  const ref = useOutsideClose(() => setOpen(false));

  return (
    <div className="relative no-drag" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-md px-2 py-1 text-2xs text-soft transition hover:bg-raised hover:text-ink"
        title={running ? "Agents running" : "Agents stopped"}
      >
        <Dot tone={running ? "good" : "bad"} pulse={running} />
        {engine.isPending ? "working" : running ? "engine on" : "engine off"}
        <ChevronDown className="h-3 w-3" />
      </button>

      {open && (
        <div className="absolute right-0 top-8 z-50 w-56 overflow-hidden rounded-xl border border-line bg-surface shadow-lg">
          <button
            className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm text-ink transition hover:bg-raised disabled:opacity-50"
            disabled={engine.isPending || running}
            onClick={() => {
              engine.mutate("start");
              setOpen(false);
            }}
          >
            <Play className="h-3.5 w-3.5" /> Start agents
          </button>
          <button
            className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm text-ink transition hover:bg-raised disabled:opacity-50"
            disabled={engine.isPending || !running}
            onClick={() => {
              engine.mutate("restart");
              setOpen(false);
            }}
          >
            <RefreshCw className="h-3.5 w-3.5" /> Restart agents
          </button>
          <button
            className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm text-down transition hover:bg-raised disabled:opacity-50"
            disabled={engine.isPending || !running}
            onClick={() => {
              engine.mutate("stop");
              setOpen(false);
            }}
          >
            <Power className="h-3.5 w-3.5" /> Stop agents
          </button>
          <p className="border-t border-line px-3 py-2 text-2xs text-faint">
            Stopping keeps the app and your data open — it only stops trading activity.
          </p>
        </div>
      )}
    </div>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 16D54186B69E - verify with scripts/authorship.py verify
