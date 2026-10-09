import { AlertTriangle, ChevronDown, ChevronUp, Circle as CircleIcon, Crosshair, LocateFixed, Loader2, MapPin, Search, Square, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import type L from "leaflet";
import { analyzeLandings, createPlans, getAirspaces, getBeacons, getSensitiveAreas, getSites, isDemoMode } from "../api/client";
import { ApiError } from "../api/errors";
import { lastResults, rememberResults } from "../api/planCache";
import type { ForecastGridResponse, GridLayer, Horizon, LandingAnalyzeRequest, LandingAnalyzeResponse, PlanRequest, PlanResponse, Zone } from "../api/types";
import { AirspacesLayer, SensitiveAreasLayer } from "../components/map/AreaLayers";
import { BeaconMarkers } from "../components/map/BeaconMarkers";
import { FitTo, InvalidateOnResize } from "../components/map/FitTo";
import { FreeTakeoffMarker, GlideConeLayer, LandingCandidateMarkers, MapPointPicker } from "../components/map/LandingLayers";
import { PioupiouAttribution } from "../components/map/StationLayers";
import { LayersMenu, ZoomButtons } from "../components/map/MapControls";
import { MapShell } from "../components/map/MapShell";
import { RouteLayer } from "../components/map/PlanLayers";
import { SiteMarkers } from "../components/map/SiteMarkers";
import { GridLegend, WeatherGridLayer } from "../components/map/WeatherGrid";
import { WEATHER_LAYERS, WIND_ALTITUDE_OPTIONS, type WeatherLayerChoice } from "../components/map/weatherLayers";
import { ZoneEditor, type DrawMode } from "../components/map/ZoneEditor";
import { CriteriaPanel } from "../components/planner/CriteriaPanel";
import {
  DEFAULT_CRITERIA,
  buildLandingAnalyzeRequest,
  buildPlanRequest,
  isCriteria,
  isFreeTakeoff,
  planRequestError,
  withCriteriaDefaults,
  type Criteria,
  type FreeTakeoff,
} from "../components/planner/criteria";
import { FreeTakeoffSection } from "../components/planner/FreeTakeoffSection";
import { LandingAnalysisPanel } from "../components/planner/LandingAnalysisPanel";
import { ResultsPanel } from "../components/planner/ResultsPanel";
import { toast } from "../components/ui/toastBus";
import { KK7, type BaseLayerId, DEFAULT_BASE_LAYER, BASE_LAYERS } from "../config/map";
import { FREE_MODE_WARNING } from "../config/labels";
import { DEFAULT_ZONE, GEOLOCATION_RADIUS_KM } from "../config/zones";
import { useAsync } from "../hooks/useAsync";
import { useIsDesktop } from "../hooks/useMediaQuery";
import { useNow } from "../hooks/useNow";
import { usePersistentState } from "../hooks/usePersistentState";
import { hasPioupiou } from "../utils/beacons";
import { haversineKm } from "../utils/geo";
import { isHorizon, targetTimeFromHorizon } from "../utils/horizon";
import { loadString, saveString } from "../utils/storage";
import { MAX_BBOX_SIDE_DEG, bboxFromCorners, padBBox, parseZone, serializeZone, validateZone, zoneToBBox } from "../utils/zone";

type Sheet = "peek" | "half" | "full";
type Tab = "criteria" | "results" | "landings";

interface Overlays {
  sites: boolean;
  beacons: boolean;
  airspaces: boolean;
  sensitive: boolean;
  kk7: boolean;
}
const DEFAULT_OVERLAYS: Overlays = { sites: true, beacons: true, airspaces: false, sensitive: true, kk7: false };
const isBase = (v: unknown): v is BaseLayerId => BASE_LAYERS.some((b) => b.id === v);
const isOverlays = (v: unknown): v is Overlays => !!v && typeof v === "object" && "sites" in (v as object);

function initialZone(params: URLSearchParams): Zone {
  return parseZone(params.get("zone")) ?? parseZone(loadString("pm.zone")) ?? DEFAULT_ZONE;
}

export function PlannerPage() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const isDesktop = useIsDesktop();
  const now = useNow();
  const [zone, setZone] = useState<Zone>(() => initialZone(params));
  const [storedCriteria, setCriteria] = usePersistentState<Criteria>("pm.criteria.v1", DEFAULT_CRITERIA, isCriteria);
  const criteria = useMemo(() => withCriteriaDefaults(storedCriteria), [storedCriteria]);
  const free = criteria.mode === "custom_takeoff";
  const [freeTakeoff, setFreeTakeoff] = usePersistentState<FreeTakeoff | null>("pm.freeTakeoff.v1", null, isFreeTakeoff);
  const [picking, setPicking] = useState(false);
  const [analysis, setAnalysis] = useState<{ request: LandingAnalyzeRequest; response: LandingAnalyzeResponse } | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [selectedLanding, setSelectedLanding] = useState<string | null>(null);
  const analyzeAbort = useRef<AbortController | null>(null);
  const [baseLayer, setBaseLayer] = usePersistentState<BaseLayerId>("pm.baseLayer", DEFAULT_BASE_LAYER, isBase);
  const [overlays, setOverlays] = usePersistentState<Overlays>("pm.overlays.planner", DEFAULT_OVERLAYS, isOverlays);
  const [weather, setWeather] = useState<WeatherLayerChoice>("none");
  const [windAlt, setWindAlt] = useState<number>(10);
  const [grid, setGrid] = useState<ForecastGridResponse | null>(null);
  const [map, setMap] = useState<L.Map | null>(null);
  const [drawMode, setDrawMode] = useState<DrawMode>("none");
  const [sheet, setSheet] = useState<Sheet>("half");
  const [tab, setTab] = useState<Tab>(() => ((location.state as { tab?: Tab } | null)?.tab === "results" && lastResults() ? "results" : "criteria"));
  const [hovered, setHovered] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [results, setResults] = useState<{ request: PlanRequest; response: PlanResponse } | null>(() => lastResults());
  const abortRef = useRef<AbortController | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  // Horizon passé dans l'URL (lien partagé) : prioritaire sur la valeur mémorisée.
  useEffect(() => {
    const h = params.get("h");
    if (isHorizon(h) && h !== criteria.horizon) setCriteria({ ...criteria, horizon: h });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Zone + horizon → URL partageable + localStorage
  const zoneKey = serializeZone(zone);
  useEffect(() => {
    saveString("pm.zone", zoneKey);
    const next = new URLSearchParams(params);
    next.set("zone", zoneKey);
    next.set("h", criteria.horizon);
    if (next.toString() !== params.toString()) setParams(next, { replace: true });
  }, [zoneKey, criteria.horizon, params, setParams]);

  // décollage libre : sélection sur la carte tant qu'aucun point n'est posé
  const hasTakeoff = freeTakeoff !== null;
  useEffect(() => {
    setPicking(free && !hasTakeoff);
  }, [free, hasTakeoff]);

  const zoneError = validateZone(zone);
  // zone des couches (sites, balises…) : autour du décollage libre (arrondie pour limiter les appels), sinon la zone
  const areaZone: Zone =
    free && freeTakeoff
      ? { type: "circle", center: { lat: Math.round(freeTakeoff.lat * 10) / 10, lon: Math.round(freeTakeoff.lon * 10) / 10 }, radius_km: 25 }
      : zone;
  const areaKey = serializeZone(areaZone);
  const bbox = useMemo(() => {
    const b = padBBox(zoneToBBox(areaZone), 1.25);
    // borne la requête des sites/balises à 3° de côté
    const cLat = (b.min_lat + b.max_lat) / 2;
    const cLon = (b.min_lon + b.max_lon) / 2;
    const h = Math.min(MAX_BBOX_SIDE_DEG, b.max_lat - b.min_lat) / 2;
    const w = Math.min(MAX_BBOX_SIDE_DEG, b.max_lon - b.min_lon) / 2;
    return bboxFromCorners({ lat: cLat - h, lon: cLon - w }, { lat: cLat + h, lon: cLon + w });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [areaKey]);
  const bboxKey = `${bbox.min_lat},${bbox.min_lon},${bbox.max_lat},${bbox.max_lon}`;

  const sites = useAsync((s) => getSites(bbox, s), [bboxKey], overlays.sites);
  const beacons = useAsync((s) => getBeacons(bbox, s), [bboxKey], overlays.beacons);
  const airspaces = useAsync((s) => getAirspaces(bbox, s), [bboxKey], overlays.airspaces);
  const sensitive = useAsync((s) => getSensitiveAreas(bbox, undefined, s), [bboxKey], overlays.sensitive);

  const reference = criteria.referenceTime ? new Date(criteria.referenceTime) : now;
  const targetIso = targetTimeFromHorizon(reference, criteria.horizon).toISOString();

  const requestNow = buildPlanRequest(zone, criteria, free ? freeTakeoff : null);
  const blockError = free ? planRequestError(criteria, freeTakeoff) : zoneError;
  const analysisRequestNow = free && freeTakeoff ? buildLandingAnalyzeRequest(criteria, freeTakeoff) : null;
  const analysisStale = analysis !== null && JSON.stringify(analysis.request) !== JSON.stringify(analysisRequestNow);
  const stale = results !== null && JSON.stringify({ ...results.request, reference_time: undefined }) !== JSON.stringify({ ...requestNow, reference_time: undefined });

  const highlightIds = useMemo(() => {
    const s = new Set<string>();
    results?.response.plans.forEach((p) => {
      s.add(p.takeoff.id);
      s.add(p.landing.id);
    });
    return s;
  }, [results]);

  const search = useCallback(async () => {
    const blocking = criteria.mode === "custom_takeoff" ? planRequestError(criteria, freeTakeoff) : zoneError;
    if (blocking) {
      toast(blocking);
      return;
    }
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setSearching(true);
    setSearchError(null);
    const req = buildPlanRequest(zone, criteria, criteria.mode === "custom_takeoff" ? freeTakeoff : null);
    try {
      const response = await createPlans(req, ctrl.signal);
      rememberResults(req, response);
      setResults({ request: req, response });
      setTab("results");
      setSheet((s) => (s === "peek" ? "half" : s));
      requestAnimationFrame(() => resultsRef.current?.scrollTo({ top: 0 }));
    } catch (e) {
      if (ctrl.signal.aborted) return;
      setSearchError(e instanceof ApiError || e instanceof Error ? e.message : "Erreur inconnue");
    } finally {
      if (!ctrl.signal.aborted) setSearching(false);
    }
  }, [zone, criteria, zoneError, freeTakeoff]);

  /** Pose (ou déplace) le décollage libre ; l'altitude saisie est oubliée si le point bouge de plus de 150 m. */
  const placeTakeoff = useCallback(
    (lat: number, lon: number) => {
      setFreeTakeoff((prev) => {
        if (!prev) return { lat, lon, elevation: null, orientations: [], name: "" };
        const moved = haversineKm(prev, { lat, lon }) > 0.15;
        return { ...prev, lat, lon, elevation: moved ? null : prev.elevation };
      });
      setPicking(false);
    },
    [setFreeTakeoff],
  );

  const analyze = useCallback(async () => {
    if (!freeTakeoff) {
      toast("Pose d'abord le point de décollage sur la carte.");
      return;
    }
    analyzeAbort.current?.abort();
    const ctrl = new AbortController();
    analyzeAbort.current = ctrl;
    const req = buildLandingAnalyzeRequest(criteria, freeTakeoff);
    setAnalyzing(true);
    setAnalysisError(null);
    try {
      const response = await analyzeLandings(req, ctrl.signal);
      setAnalysis({ request: req, response });
      setSelectedLanding(null);
      setTab("landings");
      setSheet((s) => (s === "peek" ? "half" : s));
      requestAnimationFrame(() => resultsRef.current?.scrollTo({ top: 0 }));
    } catch (e) {
      if (ctrl.signal.aborted) return;
      setAnalysisError(
        e instanceof ApiError && e.status === 404
          ? "Ce serveur ne propose pas encore l'analyse des atterrissages (POST /api/landings/analyze)."
          : e instanceof Error
            ? e.message
            : "Erreur inconnue",
      );
    } finally {
      if (!ctrl.signal.aborted) setAnalyzing(false);
    }
  }, [criteria, freeTakeoff]);

  const selectLanding = (id: string) => {
    setSelectedLanding(id);
    setTab("landings");
    setSheet((s) => (s === "peek" ? "half" : s));
  };

  const locate = () => {
    if (!("geolocation" in navigator)) {
      toast("Géolocalisation indisponible sur cet appareil.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        if (criteria.mode === "custom_takeoff") placeTakeoff(pos.coords.latitude, pos.coords.longitude);
        else setZone({ type: "circle", center: { lat: pos.coords.latitude, lon: pos.coords.longitude }, radius_km: GEOLOCATION_RADIUS_KM });
      },
      (err) => {
        setLocating(false);
        toast(err.code === err.PERMISSION_DENIED ? "Position refusée : autorise la géolocalisation." : "Position introuvable.");
      },
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 120_000 },
    );
  };

  const useView = () => {
    if (!map) return;
    const b = map.getBounds();
    let z = bboxFromCorners({ lat: b.getSouth(), lon: b.getWest() }, { lat: b.getNorth(), lon: b.getEast() });
    if (validateZone(z)) {
      const c = b.getCenter();
      const h = MAX_BBOX_SIDE_DEG / 2 - 0.01;
      z = bboxFromCorners({ lat: Math.max(z.min_lat, c.lat - h), lon: Math.max(z.min_lon, c.lng - h) }, { lat: Math.min(z.max_lat, c.lat + h), lon: Math.min(z.max_lon, c.lng + h) });
    }
    setZone(z);
  };

  const zb = zoneToBBox(zone);
  const fitBounds: [[number, number], [number, number]] = [
    [zb.min_lat, zb.min_lon],
    [zb.max_lat, zb.max_lon],
  ];
  const plans = results?.response.plans ?? [];
  // décollage libre : recadrage sur le cône de finesse à chaque nouvelle analyse (jamais en posant le point)
  const coneFit = useMemo(() => {
    if (!analysis) return null;
    const ring = analysis.response.glide_cone.coordinates[0] ?? [];
    if (ring.length < 3) return null;
    const lats = ring.map((c) => c[1]!);
    const lons = ring.map((c) => c[0]!);
    return {
      bounds: [
        [Math.min(...lats), Math.min(...lons)],
        [Math.max(...lats), Math.max(...lons)],
      ] as [[number, number], [number, number]],
      key: `cone:${JSON.stringify(analysis.request)}`,
    };
  }, [analysis]);
  // en entrant en mode libre avec un déco mémorisé : recentrage une fois (jamais lors d'un clic de pose)
  const entryFit = useMemo<[[number, number], [number, number]] | null>(
    () =>
      free && freeTakeoff
        ? [
            [freeTakeoff.lat - 0.08, freeTakeoff.lon - 0.11],
            [freeTakeoff.lat + 0.08, freeTakeoff.lon + 0.11],
          ]
        : null,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [free],
  );
  const showPioupiou = overlays.beacons && !!beacons.data && hasPioupiou(beacons.data.beacons);
  const sheetClass = isDesktop ? "" : ` planner--sheet-${sheet}`;
  // hauteur masquée par le panneau mobile (pour cadrer la zone dans la partie visible)
  const mapHeight = map?.getContainer().clientHeight ?? window.innerHeight - 90;
  const sheetInset = sheet === "peek" ? 172 : Math.round(mapHeight * 0.56);
  const onGridLoaded = useCallback((g: ForecastGridResponse | null) => setGrid(g), []);

  const searchButton = (
    <button type="button" className="btn btn--primary btn--block btn--lg" onClick={search} disabled={searching || !!blockError} title={blockError ?? undefined}>
      {searching ? <Loader2 size={18} className="spin" aria-hidden /> : <Search size={18} aria-hidden />}
      {searching ? "Calcul en cours…" : free ? "Trouver les meilleurs vols depuis ce point" : "Trouver les meilleurs vols"}
    </button>
  );

  return (
    <div className={`planner${sheetClass}`}>
      <div className="planner__map">
        <MapShell
          ref={setMap}
          center={[45.81, 6.2]}
          zoom={10}
          baseLayer={baseLayer}
          showKk7={overlays.kk7}
          ariaLabel="Carte de planification"
          overlay={
            <>
              <div className="map-overlay map-overlay--tr">
                <LayersMenu
                  baseLayer={baseLayer}
                  onBaseLayer={setBaseLayer}
                  overlays={[
                    { id: "sites", label: "Sites (déco / atterro)", checked: overlays.sites, onChange: (v) => setOverlays({ ...overlays, sites: v }) },
                    { id: "beacons", label: "Balises vent temps réel", checked: overlays.beacons, onChange: (v) => setOverlays({ ...overlays, beacons: v }) },
                    { id: "sensitive", label: "Zones sensibles (faune, parcs)", checked: overlays.sensitive, onChange: (v) => setOverlays({ ...overlays, sensitive: v }) },
                    { id: "airspaces", label: "Espaces aériens", checked: overlays.airspaces, onChange: (v) => setOverlays({ ...overlays, airspaces: v }) },
                    {
                      id: "kk7",
                      label: "Hotspots thermiques KK7",
                      checked: overlays.kk7 && !!KK7.url,
                      disabled: !KK7.url,
                      hint: KK7.url ? undefined : "Renseigner VITE_KK7_TILES_URL pour l'activer",
                      onChange: (v) => setOverlays({ ...overlays, kk7: v }),
                    },
                  ]}
                >
                  <WeatherPicker weather={weather} setWeather={setWeather} windAlt={windAlt} setWindAlt={setWindAlt} />
                </LayersMenu>
                <ZoomButtons map={map} />
              </div>
              <div className="map-overlay map-overlay--tl">
                {free ? (
                  <div className="map-btn-group map-btn-group--labeled" role="toolbar" aria-label="Décollage libre">
                    <button type="button" className={`map-btn${picking ? " map-btn--on" : ""}`} onClick={() => setPicking(!picking)} aria-pressed={picking} title="Poser le décollage d'un clic sur la carte">
                      <MapPin size={17} aria-hidden />
                      <span>{freeTakeoff ? "Déplacer le déco" : "Poser le déco"}</span>
                    </button>
                    <button type="button" className="map-btn" onClick={locate} title="Décoller de ma position" disabled={locating}>
                      {locating ? <Loader2 size={17} className="spin" aria-hidden /> : <LocateFixed size={17} aria-hidden />}
                      <span>Ma position</span>
                    </button>
                  </div>
                ) : (
                <div className="map-btn-group map-btn-group--labeled" role="toolbar" aria-label="Sélection de zone">
                  <button type="button" className={`map-btn${drawMode === "rect" ? " map-btn--on" : ""}`} onClick={() => setDrawMode(drawMode === "rect" ? "none" : "rect")} aria-pressed={drawMode === "rect"} title="Dessiner un rectangle">
                    <Square size={17} aria-hidden />
                    <span>Rectangle</span>
                  </button>
                  <button type="button" className={`map-btn${drawMode === "circle" ? " map-btn--on" : ""}`} onClick={() => setDrawMode(drawMode === "circle" ? "none" : "circle")} aria-pressed={drawMode === "circle"} title="Placer un cercle">
                    <CircleIcon size={17} aria-hidden />
                    <span>Cercle</span>
                  </button>
                  <button type="button" className="map-btn" onClick={locate} title={`Ma position (rayon ${GEOLOCATION_RADIUS_KM} km)`} disabled={locating}>
                    {locating ? <Loader2 size={17} className="spin" aria-hidden /> : <LocateFixed size={17} aria-hidden />}
                    <span>Ma position</span>
                  </button>
                  <button type="button" className="map-btn" onClick={useView} title="Utiliser la vue actuelle comme zone">
                    <Crosshair size={17} aria-hidden />
                    <span>Vue</span>
                  </button>
                </div>
                )}
              </div>
              {free && picking ? (
                <div className="map-hint" role="status">
                  Touche la carte pour poser le décollage
                  {freeTakeoff ? (
                    <button type="button" className="icon-btn icon-btn--sm" onClick={() => setPicking(false)} aria-label="Annuler">
                      <X size={16} />
                    </button>
                  ) : null}
                </div>
              ) : null}
              {!free && drawMode !== "none" ? (
                <div className="map-hint" role="status">
                  {drawMode === "rect" ? "Touche deux coins opposés du rectangle" : "Touche le centre de la zone"}
                  <button type="button" className="icon-btn icon-btn--sm" onClick={() => setDrawMode("none")} aria-label="Annuler le dessin">
                    <X size={16} />
                  </button>
                </div>
              ) : null}
              {weather !== "none" ? (
                <div className="map-overlay map-overlay--legend">
                  <GridLegend layer={weather} grid={grid} />
                </div>
              ) : null}
            </>
          }
        >
          <InvalidateOnResize />
          <FitTo
            bounds={free ? (coneFit?.bounds ?? entryFit) : fitBounds}
            fitKey={free ? (coneFit?.key ?? "free-entry") : zoneKey}
            padding={isDesktop ? 40 : 16}
            maxZoom={free ? 13 : 12}
            bottomInset={isDesktop ? 0 : sheetInset}
          />
          {weather !== "none" ? <WeatherGridLayer bbox={padBBox(zoneToBBox(zone), 1.15)} time={targetIso} layer={weather as GridLayer} altitude={windAlt} onLoaded={onGridLoaded} /> : null}
          {overlays.airspaces && airspaces.data ? <AirspacesLayer features={airspaces.data.features} /> : null}
          {overlays.sensitive && sensitive.data ? <SensitiveAreasLayer features={sensitive.data.features} /> : null}
          {free ? null : <ZoneEditor zone={zone} onChange={setZone} mode={drawMode} onModeDone={() => setDrawMode("none")} />}
          {free && analysis ? <GlideConeLayer cone={analysis.response.glide_cone} stale={analysisStale} /> : null}
          {plans.map((p) => (
            <RouteLayer key={p.id} plan={p} dim={hovered !== null && hovered !== p.id} highlight={hovered === p.id} />
          ))}
          {overlays.sites && sites.data ? <SiteMarkers sites={sites.data.sites} highlightIds={highlightIds} /> : null}
          {overlays.beacons && beacons.data ? <BeaconMarkers beacons={beacons.data.beacons} level={criteria.difficulty} now={now} /> : null}
          {free && analysis ? <LandingCandidateMarkers candidates={analysis.response.candidates} selectedId={selectedLanding} onSelect={selectLanding} /> : null}
          {free ? <MapPointPicker active={picking} onPick={placeTakeoff} /> : null}
          {free && freeTakeoff ? <FreeTakeoffMarker takeoff={freeTakeoff} onMove={placeTakeoff} /> : null}
          <PioupiouAttribution active={showPioupiou} />
        </MapShell>
      </div>

      <aside className="planner__panel" aria-label="Critères et résultats">
        {!isDesktop ? (
          <button
            type="button"
            className="sheet-handle"
            onClick={() => setSheet(sheet === "peek" ? "half" : sheet === "half" ? "full" : "peek")}
            aria-label={sheet === "full" ? "Réduire le panneau" : "Agrandir le panneau"}
          >
            <span className="sheet-handle__bar" />
            {sheet === "full" ? <ChevronDown size={18} aria-hidden /> : <ChevronUp size={18} aria-hidden />}
          </button>
        ) : null}
        <div className="tabs" role="tablist" aria-label="Panneau">
          <button type="button" role="tab" aria-selected={tab === "criteria"} className={`tab${tab === "criteria" ? " tab--on" : ""}`} onClick={() => { setTab("criteria"); if (sheet === "peek") setSheet("half"); }}>
            Critères
          </button>
          <button type="button" role="tab" aria-selected={tab === "results"} className={`tab${tab === "results" ? " tab--on" : ""}`} onClick={() => { setTab("results"); if (sheet === "peek") setSheet("half"); }} disabled={!results}>
            Résultats{results ? ` (${results.response.plans.length})` : ""}
          </button>
          {free ? (
            <button type="button" role="tab" aria-selected={tab === "landings"} className={`tab${tab === "landings" ? " tab--on" : ""}`} onClick={() => { setTab("landings"); if (sheet === "peek") setSheet("half"); }} disabled={!analysis}>
              Atterros{analysis ? ` (${analysis.response.candidates.length})` : ""}
            </button>
          ) : null}
        </div>
        <div className="planner__scroll" ref={resultsRef}>
          {tab === "landings" && free && analysis ? (
            <LandingAnalysisPanel
              analysis={analysis.response}
              level={criteria.difficulty}
              stale={analysisStale}
              selectedId={selectedLanding}
              onSelect={setSelectedLanding}
              onReanalyze={analyze}
              now={now}
              demo={isDemoMode()}
            />
          ) : tab === "criteria" || tab === "landings" || !results ? (
            <CriteriaPanel
              criteria={criteria}
              setCriteria={setCriteria}
              zone={zone}
              onZone={setZone}
              now={now}
              placeSection={
                free ? (
                  <FreeTakeoffSection
                    criteria={criteria}
                    setCriteria={setCriteria}
                    takeoff={freeTakeoff}
                    onTakeoff={setFreeTakeoff}
                    picking={picking}
                    onPicking={setPicking}
                    onLocate={locate}
                    locating={locating}
                    onAnalyze={analyze}
                    analyzing={analyzing}
                    analysisError={analysisError}
                    analysis={analysis?.response ?? null}
                    analysisStale={analysisStale}
                    onShowAnalysis={() => setTab("landings")}
                  />
                ) : undefined
              }
            />
          ) : (
            <ResultsPanel
              response={results.response}
              level={criteria.difficulty}
              stale={stale}
              hovered={hovered}
              onHover={setHovered}
              onTryHorizon={(h: Horizon) => {
                setCriteria({ ...criteria, horizon: h });
                setTab("criteria");
              }}
              now={now}
            />
          )}
        </div>
        <div className="planner__cta">
          {searchError ? (
            <div className="alert alert--danger" role="alert">
              {searchError}
            </div>
          ) : null}
          {free ? (
            <p className="alert alert--caution free-warning free-warning--cta" role="note">
              <AlertTriangle size={15} aria-hidden />
              <span>{FREE_MODE_WARNING}.</span>
            </p>
          ) : null}
          {free && blockError ? <p className="hint hint--center">{blockError}</p> : null}
          {searchButton}
        </div>
      </aside>
    </div>
  );
}

function WeatherPicker({
  weather,
  setWeather,
  windAlt,
  setWindAlt,
}: {
  weather: WeatherLayerChoice;
  setWeather: (w: WeatherLayerChoice) => void;
  windAlt: number;
  setWindAlt: (a: number) => void;
}) {
  return (
    <fieldset>
      <legend>Météo à l'heure cible</legend>
      <label className="field-row">
        <span>Couche</span>
        <select className="select" value={weather} onChange={(e) => setWeather(e.target.value as WeatherLayerChoice)}>
          {WEATHER_LAYERS.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
            </option>
          ))}
        </select>
      </label>
      {weather === "wind" ? (
        <label className="field-row">
          <span>Altitude</span>
          <select className="select" value={windAlt} onChange={(e) => setWindAlt(Number(e.target.value))}>
            {WIND_ALTITUDE_OPTIONS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </fieldset>
  );
}
