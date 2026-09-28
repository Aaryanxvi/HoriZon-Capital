// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-C20EB9E4B76F
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { Shell } from "@/components/Shell";
import { Loading } from "@/components/ui";
import { useLiveFeed } from "@/lib/live";

const OverviewPage = lazy(() => import("@/pages/OverviewPage"));
const PortfolioPage = lazy(() => import("@/pages/PortfolioPage"));
const TradingPage = lazy(() => import("@/pages/TradingPage"));
const SignalsPage = lazy(() => import("@/pages/SignalsPage"));
const AgentsPage = lazy(() => import("@/pages/AgentsPage"));
const DebatesPage = lazy(() => import("@/pages/DebatesPage"));
const RiskPage = lazy(() => import("@/pages/RiskPage"));
const PerformancePage = lazy(() => import("@/pages/PerformancePage"));
const TerminalPage = lazy(() => import("@/pages/TerminalPage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));

export default function App() {
  useLiveFeed();

  return (
    <Shell>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="/trades" element={<TradingPage />} />
          <Route path="/signals" element={<SignalsPage />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/debates" element={<DebatesPage />} />
          <Route path="/risk" element={<RiskPage />} />
          <Route path="/performance" element={<PerformancePage />} />
          <Route path="/terminal" element={<TerminalPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Shell>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token C20EB9E4B76F - verify with scripts/authorship.py verify
