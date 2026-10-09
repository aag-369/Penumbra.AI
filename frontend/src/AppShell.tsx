/**
 * The application behind "Launch App".
 *
 * Loaded lazily from `App.tsx`, so the landing page at `/` does not pay for the
 * app's pages, its state, or its storage bootstrap on first paint.
 */

import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import { Spinner } from "./components/ui";
import AdminPage from "./pages/AdminPage";
import AdvisorPage from "./pages/AdvisorPage";
import CryptoLabPage from "./pages/CryptoLabPage";
import DashboardPage from "./pages/DashboardPage";
import KeysPage from "./pages/KeysPage";
import LoginPage from "./pages/LoginPage";
import PortfolioPage from "./pages/PortfolioPage";
import { AppProvider, useApp } from "./store/AppContext";

export function Booting() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Spinner className="h-6 w-6 text-umbra" />
    </div>
  );
}

function AppRoutes() {
  const { ready, user } = useApp();
  if (!ready) return <Booting />;

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/dashboard" replace />} />
      <Route element={<Layout />}>
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="keys" element={<KeysPage />} />
        <Route path="portfolio" element={<PortfolioPage />} />
        <Route path="advisor" element={<AdvisorPage />} />
        <Route path="lab" element={<CryptoLabPage />} />
        <Route
          path="admin"
          element={user.role === "admin" ? <AdminPage /> : <Navigate to="/dashboard" replace />}
        />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
}

export default function AppShell() {
  return (
    <AppProvider>
      <AppRoutes />
    </AppProvider>
  );
}
