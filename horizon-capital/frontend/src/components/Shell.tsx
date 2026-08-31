import clsx from "clsx";
import {
  Activity,
  BarChart3,
  Bot,
  Briefcase,
  Home,
  Minus,
  Moon,
  MessagesSquare,
  Radio,
  Settings,
  ShieldAlert,
  Square,
  Sun,
  Terminal,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { useOverview, usePending } from "@/lib/api";
import { useLiveStore } from "@/lib/live";
import { EngineButton, HaltButton, ModeSwitcher } from "@/components/Controls";
import { Dot } from "@/components/ui";
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
  { to: "/trades", label: "Trading", icon: Activity },
  { to: "/signals", label: "Signals", icon: Radio },
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/debates", label: "Debates", icon: MessagesSquare },
  { to: "/risk", label: "Risk", icon: ShieldAlert },
  { to: "/performance", label: "Performance", icon: BarChart3 },
  { to: "/terminal", label: "Terminal", icon: Terminal },
];

function useTheme() {
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (localStorage.getItem("horizon-theme") as "light" | "dark") ?? "light",
  );
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("horizon-theme", theme);
  }, [theme]);
  return { theme, toggle: () => setTheme((t) => (t === "light" ? "dark" : "light")) };
}

function TitleBar() {
  const { theme, toggle } = useTheme();
  const connected = useLiveStore((s) => s.connected);
  const { data } = useOverview();
  const controls = window.horizon;

  return (
    <header className="drag flex h-11 shrink-0 items-center justify-between border-b border-line bg-rail pl-3 pr-0">
      <div className="flex items-center gap-2.5">
        <span className="grid h-5 w-5 place-items-center rounded bg-clay text-[10px] font-bold text-white">
          H
        </span>
        <span className="text-sm font-semibold tracking-tight text-ink">Horizon Capital</span>
        {data?.regime && (
          <span className="hidden items-center rounded-md border border-line px-1.5 py-0.5 text-2xs font-medium text-soft lg:inline-flex">
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
          className="no-drag mr-2 flex items-center gap-1.5 rounded-md px-2 py-1 text-2xs text-soft"
          title={connected ? "Live event stream connected" : "Reconnecting to the backend"}
        >
          <Dot tone={connected ? "good" : "bad"} pulse={connected} />
          {connected ? "live" : "offline"}
        </span>

        <button
          onClick={toggle}
          className="no-drag rounded-md p-1.5 text-soft transition hover:bg-raised hover:text-ink"
          title={theme === "light" ? "Switch to dark" : "Switch to light"}
        >
          {theme === "light" ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
        </button>

        {controls && (
          <div className="no-drag ml-1 flex items-center">
            <button
              onClick={() => controls.minimize()}
              className="px-3 py-3 text-soft transition hover:bg-raised hover:text-ink"
              title="Minimize"
            >
              <Minus className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => controls.maximize()}
              className="px-3 py-3 text-soft transition hover:bg-raised hover:text-ink"
              title="Maximize"
            >
              <Square className="h-3 w-3" />
            </button>
            <button
              onClick={() => controls.close()}
              className="px-3 py-3 text-soft transition hover:bg-down hover:text-white"
              title="Close"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>
    </header>
  );
}

function Sidebar() {
  const { data: overview } = useOverview();
  const { data: pending } = usePending();
  const pendingCount = pending?.pending.length ?? 0;
  const location = useLocation();

  return (
    <nav className="flex w-[212px] shrink-0 flex-col border-r border-line bg-rail">
      <div className="flex-1 space-y-0.5 overflow-y-auto p-2">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              clsx(
                "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition",
                isActive
                  ? "bg-surface font-medium text-ink shadow-sm"
                  : "text-soft hover:bg-surface/60 hover:text-ink",
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span className="flex-1 truncate">{label}</span>
            {to === "/trades" && pendingCount > 0 && (
              <span className="rounded-full bg-clay px-1.5 py-0.5 text-2xs font-semibold text-white">
                {pendingCount}
              </span>
            )}
          </NavLink>
        ))}
      </div>

      <div className="space-y-2 border-t border-line p-2">
        <NavLink
          to="/settings"
          className={clsx(
            "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition",
            location.pathname === "/settings"
              ? "bg-surface font-medium text-ink shadow-sm"
              : "text-soft hover:bg-surface/60 hover:text-ink",
          )}
        >
          <Settings className="h-4 w-4" />
          Settings
        </NavLink>

        {overview && (
          <div className="rounded-lg border border-line bg-surface/60 px-2.5 py-2">
            <div className="flex items-center justify-between text-2xs text-faint">
              <span>AGENTS</span>
              <span className="nums text-soft">
                {overview.agents_running}/{overview.agents_total}
              </span>
            </div>
            <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-line">
              <div
                className="h-full rounded-full bg-up transition-all"
                style={{
                  width: `${
                    overview.agents_total
                      ? (overview.agents_running / overview.agents_total) * 100
                      : 0
                  }%`,
                }}
              />
            </div>
            {(overview.halted || overview.kill_switch) && (
              <p className="mt-2 text-2xs font-semibold uppercase text-down">
                {overview.kill_switch ? "Kill switch" : "Halted"}
              </p>
            )}
          </div>
        )}
      </div>
    </nav>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full flex-col">
      <TitleBar />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-y-auto bg-paper">
          <div className="mx-auto max-w-[1200px] animate-fade-in p-6">{children}</div>
        </main>
      </div>
      <Onboarding />
    </div>
  );
}
