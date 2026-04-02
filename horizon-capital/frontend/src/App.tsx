import { Routes, Route, Navigate, Outlet } from "react-router-dom";
import Sidebar from "@/components/layout/Sidebar";
import TitleBar from "@/components/layout/TitleBar";

// Lazy-loaded pages
import { lazy, Suspense } from "react";

const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const PortfolioPage = lazy(() => import("@/pages/PortfolioPage"));
const AgentsPage = lazy(() => import("@/pages/AgentsPage"));
const TradesPage = lazy(() => import("@/pages/TradesPage"));
const RiskPage = lazy(() => import("@/pages/RiskPage"));
const PerformancePage = lazy(() => import("@/pages/PerformancePage"));
const CIOPage = lazy(() => import("@/pages/CIOPage"));

function LoadingFallback() {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="flex flex-col items-center gap-3">
        <div className="w-6 h-6 border-2 border-accent-blue border-t-transparent rounded-full animate-spin" />
        <span className="text-gray-500 text-xs">Loading...</span>
      </div>
    </div>
  );
}

function AppLayout() {
  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TitleBar />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-y-auto bg-horizon-darker p-6">
          <Suspense fallback={<LoadingFallback />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/trades" element={<TradesPage />} />
          <Route path="/risk" element={<RiskPage />} />
          <Route path="/performance" element={<PerformancePage />} />
          <Route path="/cio" element={<CIOPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
