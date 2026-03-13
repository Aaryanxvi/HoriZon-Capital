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
  Menu,
  X,
  Hexagon,
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

const MODE_COLORS: Record<string, string> = {
  autonomous: "bg-accent-red text-white",
  supervised: "bg-accent-yellow text-black",
  manual: "bg-accent-blue text-white",
};

const MODE_LABELS: Record<string, string> = {
  autonomous: "AUTO",
  supervised: "HUMAN",
  manual: "PAPER",
};

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const mode = useSystemStore((s) => s.mode);

  const sidebarContent = (
    <div className="flex flex-col h-full">
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 py-5 border-b border-horizon-border">
        <div className="relative">
          <Hexagon className="w-8 h-8 text-accent-blue" strokeWidth={1.5} />
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-2 h-2 bg-accent-blue rounded-full" />
          </div>
        </div>
        <AnimatePresence>
          {!collapsed && (
            <motion.div
              initial={{ opacity: 0, width: 0 }}
              animate={{ opacity: 1, width: "auto" }}
              exit={{ opacity: 0, width: 0 }}
              className="overflow-hidden whitespace-nowrap"
            >
              <h1 className="text-lg font-bold text-white tracking-tight">
                Horizon<span className="text-accent-blue">Capital</span>
              </h1>
              <p className="text-[10px] text-gray-500 -mt-0.5 tracking-wider uppercase">
                AI Trading System
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 px-2 space-y-1">
        {NAV_ITEMS.map(({ to, icon: Icon, label }) => {
          const isActive =
            to === "/" ? location.pathname === "/" : location.pathname.startsWith(to);
          return (
            <NavLink
              key={to}
              to={to}
              onClick={() => setMobileOpen(false)}
              className={clsx(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200",
                isActive
                  ? "bg-accent-blue/10 text-accent-blue border border-accent-blue/20"
                  : "text-gray-400 hover:text-gray-200 hover:bg-white/5 border border-transparent"
              )}
            >
              <Icon className="w-5 h-5 flex-shrink-0" />
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
              {isActive && (
                <motion.div
                  layoutId="sidebar-active"
                  className="absolute left-0 w-0.5 h-6 bg-accent-blue rounded-r-full"
                />
              )}
            </NavLink>
          );
        })}
      </nav>

      {/* Mode Badge */}
      <div className="px-4 py-4 border-t border-horizon-border">
        <div
          className={clsx(
            "flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-bold tracking-wider",
            MODE_COLORS[mode]
          )}
        >
          <div className="w-2 h-2 rounded-full bg-current animate-pulse" />
          {!collapsed && <span>{MODE_LABELS[mode]} MODE</span>}
        </div>
      </div>

      {/* Collapse Toggle (desktop) */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="hidden lg:flex items-center justify-center py-3 border-t border-horizon-border text-gray-500 hover:text-gray-300 transition-colors"
      >
        <Menu className="w-4 h-4" />
      </button>
    </div>
  );

  return (
    <>
      {/* Mobile menu button */}
      <button
        onClick={() => setMobileOpen(true)}
        className="lg:hidden fixed top-4 left-4 z-50 p-2 bg-horizon-card rounded-lg border border-horizon-border text-gray-400"
      >
        <Menu className="w-5 h-5" />
      </button>

      {/* Mobile overlay */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setMobileOpen(false)}
            className="lg:hidden fixed inset-0 bg-black/60 z-40"
          />
        )}
      </AnimatePresence>

      {/* Mobile sidebar */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.aside
            initial={{ x: -280 }}
            animate={{ x: 0 }}
            exit={{ x: -280 }}
            transition={{ type: "spring", damping: 25, stiffness: 250 }}
            className="lg:hidden fixed left-0 top-0 bottom-0 w-64 bg-horizon-dark border-r border-horizon-border z-50"
          >
            <button
              onClick={() => setMobileOpen(false)}
              className="absolute top-4 right-4 text-gray-500 hover:text-gray-300"
            >
              <X className="w-5 h-5" />
            </button>
            {sidebarContent}
          </motion.aside>
        )}
      </AnimatePresence>

      {/* Desktop sidebar */}
      <motion.aside
        animate={{ width: collapsed ? 72 : 240 }}
        transition={{ type: "spring", damping: 25, stiffness: 250 }}
        className="hidden lg:block flex-shrink-0 bg-horizon-dark border-r border-horizon-border h-screen overflow-hidden relative"
      >
        {sidebarContent}
      </motion.aside>
    </>
  );
}
