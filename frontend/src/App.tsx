import { useEffect } from "react";
import { Route, Routes } from "react-router-dom";
import { checkBackend } from "./api/client";
import { AppHeader } from "./components/layout/AppHeader";
import { DemoBanner } from "./components/layout/DemoBanner";
import { MapPatterns } from "./components/map/MapPatterns";
import { ToastHost } from "./components/ui/toast";
import { AboutPage } from "./pages/AboutPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PlanDetailPage } from "./pages/PlanDetailPage";
import { PlannerPage } from "./pages/PlannerPage";
import { SourcesPage } from "./pages/SourcesPage";

export function App() {
  useEffect(() => {
    void checkBackend();
  }, []);
  return (
    <div className="app">
      <a href="#main" className="skip-link">
        Aller au contenu
      </a>
      <AppHeader />
      <DemoBanner />
      <main id="main" className="app-main">
        <Routes>
          <Route path="/" element={<PlannerPage />} />
          <Route path="/plan/:id" element={<PlanDetailPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/a-propos" element={<AboutPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
      <MapPatterns />
      <ToastHost />
    </div>
  );
}
