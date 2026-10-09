import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

import LandingPage from "./landing/LandingPage";

// The app is a separate chunk: visitors to `/` download the landing page only.
const AppShell = lazy(() => import("./AppShell"));

function Loading() {
  return (
    <div className="flex min-h-screen items-center justify-center" role="status" aria-label="Loading">
      <span className="h-6 w-6 animate-spin rounded-full border-2 border-umbra/30 border-t-umbra" />
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route
        path="*"
        element={
          <Suspense fallback={<Loading />}>
            <AppShell />
          </Suspense>
        }
      />
    </Routes>
  );
}
