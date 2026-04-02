import { NavLink, useLocation } from "react-router-dom";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard,
  Briefcase,
  Bot,
  ArrowLeftRight,
  ShieldAlert,
  TrendingUp,
  Terminal,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react";
import clsx from "clsx";
import { useSystemStore } from "@/store";

const NAV_ITEMS = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/portfolio", icon: Briefcase, label: "Portfolio" },
  { to: "/agents", icon: Bot, label: "Agents" },
  { to: "/trades", icon: ArrowLeftRight, label: "Trades" },
  { to: "/risk", icon: ShieldAlert, label: "Risk" },
  { to: "/performance", icon: TrendingUp, label: "Performance" },
  { to: "/cio", icon: Terminal, label: "CIO" },
] as const;

const MODE_LABELS: Record<string, string> = {
  autonomous: "AUTO",
  supervised: "SUPERVISED",
  manual: "PAPER",
};

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(true);
  const location = useLocation();
  const mode = useSystemStore((s) => s.mode);

  return (
    <motion.aside
      animate={{ width: collapsed ? 56 : 200 }}
      transition={{ type: "spring", damping: 30, stiffness: 300 }}
      className="flex-shrink-0 bg-horizon-dark border-r border-horizon-border/50 h-full overflow-hidden flex flex-col"
    >
      {/* Nav items */}
      <nav className="flex-1 py-3 px-1.5 space-y-0.5">
        {NAV_ITEMS.map(({ to, icon: Icon, label }) => {
          const isActive =
            to === "/" ? location.pathname === "/" : location.pathname.startsWith(to);
          return (
            <NavLink
              key={to}
              to={to}
              className={clsx(
                "flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[13px] font-medium transition-all duration-150 relative",
                isActive
                  ? "bg-white/[0.08] text-white"
                  : "text-gray-500 hover:text-gray-300 hover:bg-white/[0.04]"
              )}
            >
              <Icon className={clsx("w-[18px] h-[18px] flex-shrink-0", isActive && "text-accent-blue")} />
              <AnimatePresence>
                {!collapsed && (
                  <motion.span
                    initial={{ opacity: 0, width: 0 }}
                    animate={{ opacity: 1, width: "auto" }}
                    exit={{ opacity: 0, width: 0 }}
                    className="overflow-hidden whitespace-nowrap"
                  >
                    {label}
                  </motion.span>
                )}
              </AnimatePresence>
            </NavLink>
          );
        })}
      </nav>

      {/* Bottom: mode + collapse */}
      <div className="px-2 pb-2 space-y-1">
        {/* Mode indicator */}
        <div className={clsx(
          "flex items-center justify-center gap-1.5 py-1.5 rounded-md text-[10px] font-semibold tracking-wider",
          "bg-white/[0.04] text-gray-500"
        )}>
          <div className="w-1.5 h-1.5 rounded-full bg-accent-green animate-pulse" />
          {!collapsed && <span>{MODE_LABELS[mode]}</span>}
        </div>

        {/* Collapse toggle */}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="w-full flex items-center justify-center py-1.5 text-gray-600 hover:text-gray-400 transition-colors rounded-md hover:bg-white/[0.03]"
        >
          {collapsed
            ? <ChevronsRight className="w-3.5 h-3.5" />
            : <ChevronsLeft className="w-3.5 h-3.5" />
          }
        </button>
      </div>
    </motion.aside>
  );
}
