import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes, useLocation } from "react-router-dom";
import "./index.css";
import { Logo } from "./components/ui";
import CommandCenter from "./pages/CommandCenter";
import ShipmentTwin from "./pages/ShipmentTwin";
import ReviewDesk from "./pages/ReviewDesk";
import Report from "./pages/Report";
import Insights from "./pages/Insights";

function Shell({ children }: { children: React.ReactNode }) {
  const loc = useLocation();
  const printMode = loc.pathname.startsWith("/report/");
  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded-lg px-3 py-1.5 text-sm transition ${isActive ? "bg-deck text-fog shadow-[inset_0_0_0_1px_var(--color-line)]" : "text-mute hover:text-fog"}`;
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:m-3 focus:rounded focus:bg-panel focus:p-2">Skip to content</a>
      {!printMode && (
        <header className="no-print sticky top-0 z-30 border-b border-line bg-panel/85 backdrop-blur">
          <div className="mx-auto flex max-w-[1440px] items-center gap-6 px-4 py-3 sm:px-6">
            <NavLink to="/" className="flex items-center gap-3">
              <Logo />
              <span className="leading-tight">
                <span className="block text-[15px] font-semibold tracking-tight">Shippeo</span>
                <span className="hidden text-[11px] text-mute md:block">Where shipping documents reveal their parallel realities.</span>
              </span>
            </NavLink>
            <nav aria-label="Main" className="ml-auto flex flex-wrap items-center gap-1">
              <NavLink to="/" end className={link}>Command Center</NavLink>
              <NavLink to="/review" className={link}>Review Desk</NavLink>
              <NavLink to="/insights" className={link}>Insights</NavLink>
            </nav>
          </div>
        </header>
      )}
      <main id="main" className={printMode ? "" : "mx-auto max-w-[1440px] px-4 py-6 sm:px-6"}>{children}</main>
      {!printMode && (
        <footer className="no-print mx-auto max-w-[1440px] px-6 pb-8 pt-4 text-xs text-mute">
          MVP: no login. Reviewer identity is self-declared and recorded with every decision. Gemini extracts; deterministic code compares.
        </footer>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Shell>
        <Routes>
          <Route path="/" element={<CommandCenter />} />
          <Route path="/email/:id" element={<ShipmentTwin />} />
          <Route path="/review" element={<ReviewDesk />} />
          <Route path="/report/:id" element={<Report />} />
          <Route path="/insights" element={<Insights />} />
          <Route path="*" element={<p className="p-10 text-mute">Page not found.</p>} />
        </Routes>
      </Shell>
    </BrowserRouter>
  </React.StrictMode>,
);
