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
import { useApp } from "./store/AppContext";

function Booting() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Spinner className="h-6 w-6 text-umbra" />
    </div>
  );
}

export default function App() {
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
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="keys" element={<KeysPage />} />
        <Route path="portfolio" element={<PortfolioPage />} />
        <Route path="advisor" element={<AdvisorPage />} />
        <Route path="lab" element={<CryptoLabPage />} />
        <Route
          path="admin"
          element={user.role === "admin" ? <AdminPage /> : <Navigate to="/" replace />}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
