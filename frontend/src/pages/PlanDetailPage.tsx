import { ArrowLeft, Download, FileJson, Printer, Share2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { createPlans, getPlan, getPlanExport, isDemoPlanId } from "../api/client";
import { cachedPlan, planMeta, rememberPlan, rememberResults } from "../api/planCache";
import type { FlightPlan } from "../api/types";
import { Disclaimer } from "../components/layout/Disclaimer";
import {
  AerologyBlock,
  AirspacesBlock,
  BriefingBlock,
  ChecklistBlock,
  EmergencyBlock,
  LandingBlock,
  RisksBlock,
  TechnicalBlock,
  WaypointTable,
} from "../components/plan/Blocks";
import { Emagram } from "../components/plan/Emagram";
import { LandingAnalysisBlock } from "../components/plan/LandingAnalysisBlock";
import { StationReadingsBlock } from "../components/plan/StationReadingsBlock";
import { pilotLevel } from "../components/plan/level";
import { PlanMap } from "../components/plan/PlanMap";
import { RouteProfile } from "../components/plan/RouteProfile";
import { RouteSketch } from "../components/plan/RouteSketch";
import { TimelineCharts } from "../components/plan/TimelineCharts";
import { VerdictBanner } from "../components/plan/VerdictBanner";
import { WindBlock } from "../components/plan/WindBlock";
import { WindowBlock } from "../components/plan/WindowBlock";
import { ErrorBox, Spinner } from "../components/ui/Spinner";
import { toast } from "../components/ui/toastBus";
import { THERMAL_USAGE_LABEL, flightTypeLabel } from "../config/labels";
import { useApiMode } from "../hooks/useApiMode";
import { useAsync } from "../hooks/useAsync";
import { useNow } from "../hooks/useNow";
import { copyToClipboard, downloadText } from "../utils/download";
import { safeFilename } from "../utils/exports";
import { formatDayTime, formatDuration, formatKm } from "../utils/format";
import { beaconsFirst, findEquivalentPlan, planUpdatedAt, refreshRequestFor } from "../utils/planRefresh";

/** Ouvre tous les <details> pendant l'impression (feuille de vol complète), puis restaure. */
function usePrintExpand() {
  useEffect(() => {
    let opened: HTMLDetailsElement[] = [];
    const before = () => {
      opened = Array.from(document.querySelectorAll<HTMLDetailsElement>("details:not([open])"));
      opened.forEach((d) => (d.open = true));
    };
    const after = () => {
      opened.forEach((d) => (d.open = false));
      opened = [];
    };
    window.addEventListener("beforeprint", before);
    window.addEventListener("afterprint", after);
    return () => {
      window.removeEventListener("beforeprint", before);
      window.removeEventListener("afterprint", after);
    };
  }, []);
}

export function PlanDetailPage() {
  const { id = "" } = useParams();
  const now = useNow();
  const mode = useApiMode();
  const navigate = useNavigate();
  const [refreshing, setRefreshing] = useState(false);
  usePrintExpand();
  const { data: plan, error, loading, reload } = useAsync<FlightPlan>(
    async (signal) => {
      const c = cachedPlan(id);
      if (c) return c;
      const p = await getPlan(id, signal);
      rememberPlan(p);
      return p;
    },
    [id],
  );

  // requête d'origine et heure du calcul (null pour un lien partagé)
  const meta = useMemo(() => (plan ? planMeta(plan.id) : null), [plan]);

  useEffect(() => {
    if (plan) document.title = `${plan.title} — Paraglide Manager`;
    return () => {
      document.title = "Paraglide Manager";
    };
  }, [plan]);

  if (loading && !plan) {
    return (
      <div className="page page--center">
        <Spinner label="Chargement du plan de vol…" />
      </div>
    );
  }
  if (error || !plan) {
    return (
      <div className="page page--narrow">
        <h1>Plan de vol introuvable</h1>
        <p className="muted">Les plans sont conservés quelques heures par le serveur. Relance une recherche depuis la carte.</p>
        {error ? <ErrorBox error={error} onRetry={reload} /> : null}
        <p>
          <Link to="/" className="btn btn--primary">
            Retour à la planification
          </Link>
        </p>
      </div>
    );
  }

  const offline = isDemoPlanId(plan.id) || mode === "demo-forced" || mode === "demo-fallback";
  const demo = offline || plan.sources.some((s) => s.mode === "mock");
  const level = pilotLevel(plan);
  const typeLabel = plan.flight_type === "local" && plan.thermal_usage === "none" ? "Plouf" : flightTypeLabel(plan.flight_type);

  const share = async () => {
    const url = window.location.href;
    if (navigator.share) {
      try {
        await navigator.share({ title: plan.title, text: `${plan.title} — ${plan.summary}`, url });
        return;
      } catch {
        /* annulé : repli sur la copie */
      }
    }
    toast((await copyToClipboard(url)) ? "Lien du plan copié" : url);
  };
  const { request: refreshReq, rebuilt } = refreshRequestFor(plan, meta?.request ?? null, level, now);
  const refresh = async () => {
    setRefreshing(true);
    try {
      const res = await createPlans(refreshReq);
      rememberResults(refreshReq, res);
      const eq = findEquivalentPlan(plan, res.plans);
      if (!eq) {
        toast("Ce vol n'est plus proposé avec les dernières mesures : voici les résultats à jour.");
        navigate("/", { state: { tab: "results" } });
        return;
      }
      toast("Balises et prévision actualisées.");
      if (eq.id === plan.id) reload();
      else navigate(`/plan/${encodeURIComponent(eq.id)}`, { replace: true });
    } catch (e) {
      toast(`Actualisation impossible : ${e instanceof Error ? e.message : "erreur"}`);
    } finally {
      setRefreshing(false);
    }
  };
  const live = (
    <StationReadingsBlock
      plan={plan}
      level={level}
      now={now}
      updatedAt={planUpdatedAt(plan, meta?.generated_at ?? null)}
      onRefresh={refresh}
      refreshing={refreshing}
      rebuilt={rebuilt}
    />
  );
  const liveFirst = beaconsFirst(plan, meta?.request ?? null, meta?.generated_at ?? null, now);

  const download = async (kind: "gpx" | "xctsk") => {
    try {
      const content = await getPlanExport(plan, kind);
      downloadText(safeFilename(plan.title, kind), content, kind === "gpx" ? "application/gpx+xml" : "application/json");
    } catch (e) {
      toast(`Export impossible : ${e instanceof Error ? e.message : "erreur"}`);
    }
  };

  return (
    <div className="plan-page">
      <header className="plan-head">
        <div className="plan-head__bar no-print">
          <Link to="/" className="back-link">
            <ArrowLeft size={16} aria-hidden /> Plans
          </Link>
          <div className="plan-head__actions">
            <button type="button" className="icon-btn" onClick={share} title="Partager le lien" aria-label="Partager le lien">
              <Share2 size={18} />
            </button>
            <button type="button" className="icon-btn" onClick={() => window.print()} title="Imprimer la feuille de vol" aria-label="Imprimer la feuille de vol">
              <Printer size={18} />
            </button>
          </div>
        </div>
        <div className="plan-head__main">
          <h1 className="plan-head__title">
            <span className="plan-head__rank" aria-label={`Rang ${plan.rank}`}>
              {plan.rank}
            </span>
            {plan.title}
          </h1>
          <p className="plan-head__sub">
            {typeLabel} ({THERMAL_USAGE_LABEL[plan.thermal_usage]}) · {formatDuration(plan.est_duration_min)} · {formatKm(plan.distance_km)} · cible{" "}
            {formatDayTime(plan.target_time, now)} <span className="faint">(heure locale)</span>
          </p>
        </div>
      </header>

      <div className="plan-grid">
        <div className="plan-col plan-col--top">
          <VerdictBanner plan={plan} demo={demo} offline={offline} />
          {liveFirst ? live : null}
          <WindowBlock plan={plan} level={level} />
          <WindBlock plan={plan} level={level} now={now} />
          {liveFirst ? null : live}
          <BriefingBlock plan={plan} />
        </div>

        <div className="plan-col plan-col--map">
          <div className="no-print">
            <PlanMap plan={plan} level={level} now={now} />
          </div>
          <section className="block" aria-labelledby="b-route">
            <h2 id="b-route" className="block__title">
              Itinéraire
            </h2>
            <div className="only-print">
              <RouteSketch plan={plan} />
            </div>
            <WaypointTable plan={plan} />
            <RouteProfile plan={plan} />
          </section>
        </div>

        <div className="plan-col plan-col--rest">
          <AerologyBlock plan={plan}>
            <details className="sub-details">
              <summary>Évolution détaillée au déco (±3 h)</summary>
              <TimelineCharts plan={plan} level={level} />
            </details>
            <details className="sub-details">
              <summary>Émagramme simplifié</summary>
              <Emagram sounding={plan.sounding} ceiling={plan.thermals.ceiling_m} cloudBase={plan.weather.takeoff.cloud_base_m} takeoffAlt={plan.takeoff.elevation_m} />
            </details>
          </AerologyBlock>
          <RisksBlock risks={plan.risks} />
          <LandingBlock plan={plan} level={level} />
          <LandingAnalysisBlock plan={plan} level={level} />
          <AirspacesBlock plan={plan} />
          <ChecklistBlock plan={plan} />
          <EmergencyBlock plan={plan} />
          <section className="block no-print" aria-labelledby="b-export">
            <h2 id="b-export" className="block__title">
              Exports et partage
            </h2>
            <div className="actions">
              <button type="button" className="btn" onClick={() => download("gpx")}>
                <Download size={16} aria-hidden /> GPX
              </button>
              <button type="button" className="btn" onClick={() => download("xctsk")}>
                <FileJson size={16} aria-hidden /> Tâche XCTrack
              </button>
              <button type="button" className="btn" onClick={share}>
                <Share2 size={16} aria-hidden /> Partager le lien
              </button>
              <button type="button" className="btn" onClick={() => window.print()}>
                <Printer size={16} aria-hidden /> Imprimer (A4)
              </button>
            </div>
            <p className="tiny faint">GPX 1.1 (points, route, trace prévue) pour GPS et applis ; .xctsk pour XCTrack (déco, balises, but).</p>
          </section>
          <TechnicalBlock plan={plan} now={now} />
        </div>
      </div>
      <Disclaimer />
    </div>
  );
}
