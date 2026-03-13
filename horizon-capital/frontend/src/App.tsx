import { Routes, Route, Navigate, Outlet } from "react-router-dom";
import { useAuthStore } from "@/store";
import Sidebar from "@/components/layout/Sidebar";

// Lazy-loaded pages
import { lazy, Suspense } from "react";

const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const PortfolioPage = lazy(() => import("@/pages/PortfolioPage"));
const AgentsPage = lazy(() => import("@/pages/AgentsPage"));
const TradesPage = lazy(() => import("@/pages/TradesPage"));
const RiskPage = lazy(() => import("@/pages/RiskPage"));
const PerformancePage = lazy(() => import("@/pages/PerformancePage"));
const CIOPage = lazy(() => import("@/pages/CIOPage"));
const LoginPage = lazy(() => import("@/pages/LoginPage"));

function LoadingFallback() {
  return (
    <div className="flex items-center justify-center h-screen bg-horizon-darker">
      <div className="flex flex-col items-center gap-4">
        <div className="w-8 h-8 border-2 border-accent-blue border-t-transparent rounded-full animate-spin" />
        <span className="text-gray-400 text-sm">Loading...</span>
      </div>
    </div>
  );
}

function ProtectedRoute() {
  const token = useAuthStore((s) => s.token);
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}

function AppLayout() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto bg-horizon-darker p-6">
        <Suspense fallback={<LoadingFallback />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/portfolio" element={<PortfolioPage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/trades" element={<TradesPage />} />
            <Route path="/risk" element={<RiskPage />} />
            <Route path="/performance" element={<PerformancePage />} />
            <Route path="/cio" element={<CIOPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
