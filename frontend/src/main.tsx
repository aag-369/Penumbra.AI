import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

// Self-hosted, so a privacy product makes no third-party request just to
// render its type -- and so the site works offline.
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";

import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* v7 splat-path resolution is safe here: every link in the app is absolute. v7_startTransition is
        left off -- it reorders the post-sign-up redirect so new users skip the Keys page. */}
    <BrowserRouter future={{ v7_relativeSplatPath: true }}>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
