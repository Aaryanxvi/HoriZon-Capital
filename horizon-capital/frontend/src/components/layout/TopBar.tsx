// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-46E713BF7A73
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useState, useEffect } from "react";
import { format } from "date-fns";
import { motion } from "framer-motion";
import { Wifi, WifiOff, Power, User, LogOut, ChevronDown } from "lucide-react";
import clsx from "clsx";
import { useAuthStore, useSystemStore, useRiskStore } from "@/store";

const MODE_LABELS: Record<string, string> = {
  autonomous: "FULLY AUTONOMOUS",
  supervised: "HUMAN APPROVAL",
  manual: "PAPER TRADING",
};

const MODE_COLORS: Record<string, string> = {
  autonomous: "text-accent-red",
  supervised: "text-accent-yellow",
  manual: "text-accent-blue",
};

export default function TopBar() {
  const [now, setNow] = useState(new Date());
  const [menuOpen, setMenuOpen] = useState(false);
  const { user, logout } = useAuthStore();
  const { mode, connected } = useSystemStore();
  const killSwitchActive = useRiskStore((s) => s.killSwitchActive);

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <header className="flex items-center justify-between px-6 py-3 bg-horizon-dark border-b border-horizon-border">
      {/* Left: Time + Mode */}
      <div className="flex items-center gap-6">
        <div className="text-sm">
          <span className="text-gray-400">{format(now, "EEE, dd MMM yyyy")}</span>
          <span className="text-white font-mono ml-2">{format(now, "HH:mm:ss")}</span>
        </div>

        <div
          className={clsx(
            "text-xs font-bold tracking-wider px-3 py-1 rounded border",
            MODE_COLORS[mode],
            mode === "autonomous"
              ? "border-accent-red/30 bg-accent-red/10"
              : mode === "supervised"
              ? "border-accent-yellow/30 bg-accent-yellow/10"
              : "border-accent-blue/30 bg-accent-blue/10"
          )}
        >
          {MODE_LABELS[mode]}
        </div>
      </div>

      {/* Right: Kill switch, Connection, User */}
      <div className="flex items-center gap-4">
        {/* Kill Switch Indicator */}
        {killSwitchActive && (
          <motion.div
            animate={{ opacity: [1, 0.4, 1] }}
            transition={{ duration: 1, repeat: Infinity }}
            className="flex items-center gap-2 px-3 py-1 bg-accent-red/20 border border-accent-red/40 rounded text-accent-red text-xs font-bold"
          >
            <Power className="w-3.5 h-3.5" />
            KILL SWITCH ACTIVE
          </motion.div>
        )}

        {/* Connection Status */}
        <div className="flex items-center gap-2 text-xs">
          {connected ? (
            <>
              <Wifi className="w-4 h-4 text-accent-green" />
              <span className="text-accent-green">Connected</span>
            </>
          ) : (
            <>
              <WifiOff className="w-4 h-4 text-accent-red" />
              <span className="text-accent-red">Disconnected</span>
            </>
          )}
          <div
            className={clsx(
              "w-2 h-2 rounded-full",
              connected ? "bg-accent-green animate-pulse" : "bg-accent-red"
            )}
          />
        </div>

        {/* User Menu */}
        <div className="relative">
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-white/5 transition-colors"
          >
            <div className="w-7 h-7 rounded-full bg-accent-blue/20 border border-accent-blue/30 flex items-center justify-center">
              <User className="w-4 h-4 text-accent-blue" />
            </div>
            <span className="text-sm text-gray-300 hidden sm:inline">
              {user?.username || "CIO"}
            </span>
            <ChevronDown className="w-3.5 h-3.5 text-gray-500" />
          </button>

          {menuOpen && (
            <>
              <div
                className="fixed inset-0 z-40"
                onClick={() => setMenuOpen(false)}
              />
              <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                className="absolute right-0 top-full mt-1 w-48 bg-horizon-card border border-horizon-border rounded-lg shadow-xl z-50 overflow-hidden"
              >
                <button
                  onClick={() => {
                    setMenuOpen(false);
                    logout();
                  }}
                  className="flex items-center gap-3 w-full px-4 py-3 text-sm text-gray-300 hover:bg-white/5 hover:text-white transition-colors"
                >
                  <LogOut className="w-4 h-4" />
                  Sign Out
                </button>
              </motion.div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 46E713BF7A73 - verify with scripts/authorship.py verify
