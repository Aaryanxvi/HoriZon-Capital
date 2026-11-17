// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-A2C9CB68ACA3
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import clsx from "clsx";
import {
  Activity,
  BarChart3,
  Bot,
  Briefcase,
  FlaskConical,
  Microscope,
  Home,
  ListPlus,
  Minus,
  Monitor,
  Moon,
  MessagesSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  Radio,
  Settings,
  ShieldAlert,
  Square,
  Sun,
  Terminal,
  TriangleAlert,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { useEngineControl, useOverview, usePending, usePositions } from "@/lib/api";
import { dateTime, timeAgo } from "@/lib/format";
import { useLiveStore } from "@/lib/live";
import { useThemeStore, type ThemePref } from "@/lib/theme";
import { EngineButton, HaltButton, ModeSwitcher } from "@/components/Controls";
import { Dot, IconButton, StatusChip } from "@/components/ui";
import { Onboarding } from "@/components/Onboarding";

// The Electron preload exposes window controls; in a plain browser it is absent
// and the titlebar quietly drops its buttons.
declare global {
  interface Window {
    horizon?: {
      platform: string;
      isDesktop: boolean;
      minimize: () => void;
      maximize: () => void;
      close: () => void;
    };
  }
}

const NAV = [
  { to: "/", label: "Overview", icon: Home, end: true },
  { to: "/portfolio", label: "Portfolio", icon: Briefcase },
  { to: "/watchlist", label: "Watchlist", icon: ListPlus },
  { to: "/trades", label: "Trading", icon: Activity },
  { to: "/signals", label: "Signals", icon: Radio },
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/debates", label: "Debates", icon: MessagesSquare },
  { to: "/risk", label: "Risk", icon: ShieldAlert },
  { to: "/performance", label: "Performance", icon: BarChart3 },
  { to: "/analysis", label: "Analysis", icon: Microscope },
  { to: "/backtest", label: "Backtest", icon: FlaskConical },
  { to: "/terminal", label: "Terminal", icon: Terminal },
];

const THEME: Record<ThemePref, { next: ThemePref; icon: LucideIcon; label: string }> = {
  system: { next: "light", icon: Monitor, label: "Theme: follow system" },
  light: { next: "dark", icon: Sun, label: "Theme: light" },
  dark: { next: "system", icon: Moon, label: "Theme: dark" },
};

const WINDOW_BTN = "grid h-10 w-11 place-items-center text-ink-3 transition-colors duration-100";

function TitleBar() {
  const pref = useThemeStore((s) => s.pref);
  const setPref = useThemeStore((s) => s.setPref);
  const connected = useLiveStore((s) => s.connected);
  const { data } = useOverview();
  const controls = window.horizon;
  const theme = THEME[pref];

  return (
    <header className="drag flex h-10 shrink-0 items-center justify-between border-b border-line bg-rail pl-3">
      <div className="flex items-center gap-2">
        <span className="grid h-[18px] w-[18px] place-items-center rounded-[3px] bg-accent text-[10px] font-bold text-accent-ink">
          H
        </span>
        <span className="text-sm font-semibold text-ink">Horizon Capital</span>
        {data?.regime && (
          <span className="hidden items-center rounded border border-line px-1.5 text-2xs text-ink-2 lg:inline-flex">
            regime {data.regime.toLowerCase()}
          </span>
        )}
      </div>

      {/* Controls that must always be one click away, whatever screen you are on. */}
      <div className="flex items-center gap-1.5">
        <HaltButton />
        <ModeSwitcher />
        <EngineButton />
      </div>

      <div className="flex items-center">
        <span
          className="no-drag mr-1 flex items-center gap-1.5 px-2 text-2xs text-ink-3"
          title={connected ? "Live event stream connected" : "Reconnecting to the backend"}
        >
          <Dot tone={connected ? "good" : "bad"} pulse={connected} />
          {connected ? "live" : "offline"}
        </span>

        <IconButton label={theme.label} icon={theme.icon} onClick={() => setPref(theme.next)} />

        {controls && (
          <div className="no-drag ml-1 flex items-center">
            <button
              type="button"
              onClick={() => controls.minimize()}
              className={clsx(WINDOW_BTN, "hover:bg-surface-2 hover:text-ink")}
              title="Minimize"
              aria-label="Minimize"
            >
              <Minus className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => controls.maximize()}
              className={clsx(WINDOW_BTN, "hover:bg-surface-2 hover:text-ink")}
              title="Maximize"
              aria-label="Maximize"
            >
              <Square className="h-3 w-3" />
            </button>
            <button
              type="button"
              onClick={() => controls.close()}
              className={clsx(WINDOW_BTN, "hover:bg-crit hover:text-white")}
              title="Close"
              aria-label="Close"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>
    </header>
  );
}

function NavItem({
  to,
  label,
  icon: Icon,
  end,
  collapsed,
  badge,
}: {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  collapsed: boolean;
  badge?: number;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      title={collapsed ? (badge ? `${label} · ${badge} pending` : label) : undefined}
      className={({ isActive }) =>
        clsx(
          "relative flex h-8 items-center gap-2.5 rounded text-sm transition-colors duration-100",
          collapsed ? "justify-center" : "px-2.5",
          isActive
            ? "bg-surface font-medium text-ink before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-accent"
            : "text-ink-2 hover:bg-surface/70 hover:text-ink",
        )
      }
    >
      <Icon className="h-4 w-4 shrink-0" aria-hidden />
      {collapsed ? (
        badge ? (
          <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-accent-strong" />
        ) : null
      ) : (
        <>
          <span className="flex-1 truncate">{label}</span>
          {badge ? (
            <span className="nums rounded bg-accent-strong px-1.5 text-2xs font-semibold text-accent-ink">
              {badge}
            </span>
          ) : null}
        </>
      )}
    </NavLink>
  );
}

function Sidebar() {
  const { data: overview } = useOverview();
  const { data: pending } = usePending();
  const pendingCount = pending?.pending.length ?? 0;
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("horizon-nav") === "collapsed");
  useEffect(() => localStorage.setItem("horizon-nav", collapsed ? "collapsed" : "expanded"), [collapsed]);

  const stopped = Boolean(overview?.halted || overview?.kill_switch);

  return (
    <nav
      className={clsx(
        "flex shrink-0 flex-col border-r border-line bg-rail",
        collapsed ? "w-[52px]" : "w-[200px]",
      )}
      aria-label="Main"
    >
      <div className="flex-1 space-y-0.5 overflow-y-auto p-2">
        {NAV.map((item) => (
          <NavItem
            key={item.to}
            {...item}
            collapsed={collapsed}
            badge={item.to === "/trades" && pendingCount > 0 ? pendingCount : undefined}
          />
        ))}
      </div>

      <div className="space-y-2 border-t border-line p-2">
        <NavItem to="/settings" label="Settings" icon={Settings} collapsed={collapsed} />

        {overview &&
          (collapsed ? (
            <div
              className="flex h-6 items-center justify-center"
              title={`Agents ${overview.agents_running}/${overview.agents_total}${
                stopped ? (overview.kill_switch ? " · kill switch" : " · halted") : ""
              }`}
            >
              <Dot tone={stopped ? "bad" : overview.agents_running > 0 ? "good" : "neutral"} />
            </div>
          ) : (
            <div className="rounded-md border border-line bg-surface px-2.5 py-2">
              <div className="flex items-center justify-between text-2xs text-ink-3">
                <span className="uppercase tracking-wide">Agents</span>
                <span className="nums text-ink-2">
                  {overview.agents_running}/{overview.agents_total}
                </span>
              </div>
              <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-line">
                <div
                  className="h-full rounded-full bg-ok"
                  style={{
                    width: `${
                      overview.agents_total
                        ? (overview.agents_running / overview.agents_total) * 100
                        : 0
                    }%`,
                  }}
                />
              </div>
              {stopped && (
                <StatusChip
                  tone="critical"
                  label={overview.kill_switch ? "Kill switch" : "Halted"}
                  className="mt-2"
                />
              )}
            </div>
          ))}

        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className={clsx(
            "flex h-8 w-full items-center gap-2.5 rounded text-xs text-ink-3 transition-colors duration-100 hover:bg-surface/70 hover:text-ink",
            collapsed ? "justify-center" : "px-2.5",
          )}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <PanelLeftOpen className="h-4 w-4" aria-hidden />
          ) : (
            <>
              <PanelLeftClose className="h-4 w-4" aria-hidden />
              Collapse
            </>
          )}
        </button>
      </div>
    </nav>
  );
}

/** With the engine off nothing marks positions, P&L or risk, so say how old they are. */
function EngineOffBanner() {
  const { data: overview } = useOverview();
  const { data: positions } = usePositions();
  const engine = useEngineControl();
  if (!overview || (overview.agents_live && overview.agents_running > 0)) return null;

  // Freshest mark across the book; positions are only re-marked while agents run.
  const asOf = positions?.positions.reduce<string | null>(
    (latest, p) => (!latest || p.updated_at > latest ? p.updated_at : latest),
    null,
  );

  return (
    <div className="flex items-center gap-2 border-b border-warn/40 bg-warn/15 px-4 py-1.5 text-xs text-ink">
      <TriangleAlert className="h-3.5 w-3.5 shrink-0 text-warn" aria-hidden />
      <span className="flex-1">
        <span className="font-semibold">Engine off</span>
        {" — positions, P&L and risk are frozen"}
        {asOf && ` as of ${dateTime(asOf)} (${timeAgo(asOf)})`}. Watchlist prices stay live.
        {engine.isError && <span className="ml-2 text-crit">Could not start: {engine.error.message}</span>}
      </span>
      <button
        type="button"
        disabled={engine.isPending}
        onClick={() => engine.mutate("start")}
        className="flex h-6 items-center gap-1.5 rounded bg-accent px-2.5 text-2xs font-semibold text-accent-ink transition-opacity duration-100 hover:opacity-90 disabled:opacity-50"
      >
        <Play className="h-3 w-3" aria-hidden />
        {engine.isPending ? "Starting…" : "Start engine"}
      </button>
    </div>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full flex-col">
      <TitleBar />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-y-auto bg-canvas">
          <EngineOffBanner />
          <div className="mx-auto max-w-[1600px] p-4">{children}</div>
        </main>
      </div>
      <Onboarding />
    </div>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token A2C9CB68ACA3 - verify with scripts/authorship.py verify
