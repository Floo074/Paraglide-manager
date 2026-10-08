import { ChevronDown, ChevronUp, Circle as CircleIcon, Crosshair, LocateFixed, Loader2, Search, Square, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type L from "leaflet";
import { createPlans, getAirspaces, getBeacons, getSensitiveAreas, getSites } from "../api/client";
import { ApiError } from "../api/errors";
import { lastResults, rememberResults } from "../api/planCache";
import type { ForecastGridResponse, GridLayer, Horizon, PlanRequest, PlanResponse, Zone } from "../api/types";
import { AirspacesLayer, SensitiveAreasLayer } from "../components/map/AreaLayers";
import { BeaconMarkers } from "../components/map/BeaconMarkers";
import { FitTo, InvalidateOnResize } from "../components/map/FitTo";
import { LayersMenu, ZoomButtons } from "../components/map/MapControls";
import { MapShell } from "../components/map/MapShell";
import { RouteLayer } from "../components/map/PlanLayers";
import { SiteMarkers } from "../components/map/SiteMarkers";
import { GridLegend, WEATHER_LAYERS, WIND_ALTITUDE_OPTIONS, WeatherGridLayer, type WeatherLayerChoice } from "../components/map/WeatherGrid";
import { ZoneEditor, type DrawMode } from "../components/map/ZoneEditor";
import { CriteriaPanel } from "../components/planner/CriteriaPanel";
import { DEFAULT_CRITERIA, buildPlanRequest, isCriteria, type Criteria } from "../components/planner/criteria";
import { ResultsPanel } from "../components/planner/ResultsPanel";
import { toast } from "../components/ui/toast";
import { KK7, type BaseLayerId, DEFAULT_BASE_LAYER, BASE_LAYERS } from "../config/map";
import { DEFAULT_ZONE, GEOLOCATION_RADIUS_KM } from "../config/zones";
import { useAsync } from "../hooks/useAsync";
import { useIsDesktop } from "../hooks/useMediaQuery";
import { useNow } from "../hooks/useNow";
import { usePersistentState } from "../hooks/usePersistentState";
import { isHorizon, targetTimeFromHorizon } from "../utils/horizon";
import { loadString, saveString } from "../utils/storage";
import { MAX_BBOX_SIDE_DEG, bboxFromCorners, padBBox, parseZone, serializeZone, validateZone, zoneToBBox } from "../utils/zone";

type Sheet = "peek" | "half" | "full";
type Tab = "criteria" | "results";

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
  const isDesktop = useIsDesktop();
  const now = useNow();
  const [zone, setZone] = useState<Zone>(() => initialZone(params));
  const [criteria, setCriteria] = usePersistentState<Criteria>("pm.criteria.v1", DEFAULT_CRITERIA, isCriteria);
  const [baseLayer, setBaseLayer] = usePersistentState<BaseLayerId>("pm.baseLayer", DEFAULT_BASE_LAYER, isBase);
  const [overlays, setOverlays] = usePersistentState<Overlays>("pm.overlays.planner", DEFAULT_OVERLAYS, isOverlays);
  const [weather, setWeather] = useState<WeatherLayerChoice>("none");
  const [windAlt, setWindAlt] = useState<number>(10);
  const [grid, setGrid] = useState<ForecastGridResponse | null>(null);
  const [map, setMap] = useState<L.Map | null>(null);
  const [drawMode, setDrawMode] = useState<DrawMode>("none");
  const [sheet, setSheet] = useState<Sheet>("half");
  const [tab, setTab] = useState<Tab>("criteria");
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

  const zoneError = validateZone(zone);
  const bbox = useMemo(() => {
    const b = padBBox(zoneToBBox(zone), 1.25);
    // borne la requête des sites/balises à 3° de côté
    const cLat = (b.min_lat + b.max_lat) / 2;
    const cLon = (b.min_lon + b.max_lon) / 2;
    const h = Math.min(MAX_BBOX_SIDE_DEG, b.max_lat - b.min_lat) / 2;
    const w = Math.min(MAX_BBOX_SIDE_DEG, b.max_lon - b.min_lon) / 2;
    return bboxFromCorners({ lat: cLat - h, lon: cLon - w }, { lat: cLat + h, lon: cLon + w });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoneKey]);
  const bboxKey = `${bbox.min_lat},${bbox.min_lon},${bbox.max_lat},${bbox.max_lon}`;

  const sites = useAsync((s) => getSites(bbox, s), [bboxKey], overlays.sites);
  const beacons = useAsync((s) => getBeacons(bbox, s), [bboxKey], overlays.beacons);
  const airspaces = useAsync((s) => getAirspaces(bbox, s), [bboxKey], overlays.airspaces);
  const sensitive = useAsync((s) => getSensitiveAreas(bbox, undefined, s), [bboxKey], overlays.sensitive);

  const reference = criteria.referenceTime ? new Date(criteria.referenceTime) : now;
  const targetIso = targetTimeFromHorizon(reference, criteria.horizon).toISOString();

  const requestNow = buildPlanRequest(zone, criteria);
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
    if (zoneError) {
      toast(zoneError);
      return;
    }
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setSearching(true);
    setSearchError(null);
    const req = buildPlanRequest(zone, criteria);
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
  }, [zone, criteria, zoneError]);

  const locate = () => {
    if (!("geolocation" in navigator)) {
      toast("Géolocalisation indisponible sur cet appareil.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        setZone({ type: "circle", center: { lat: pos.coords.latitude, lon: pos.coords.longitude }, radius_km: GEOLOCATION_RADIUS_KM });
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
  const sheetClass = isDesktop ? "" : ` planner--sheet-${sheet}`;
  const onGridLoaded = useCallback((g: ForecastGridResponse | null) => setGrid(g), []);

  const searchButton = (
    <button type="button" className="btn btn--primary btn--block btn--lg" onClick={search} disabled={searching || !!zoneError}>
      {searching ? <Loader2 size={18} className="spin" aria-hidden /> : <Search size={18} aria-hidden />}
      {searching ? "Calcul en cours…" : "Trouver les meilleurs vols"}
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
              </div>
              {drawMode !== "none" ? (
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
          <FitTo bounds={fitBounds} fitKey={zoneKey} padding={isDesktop ? 40 : 20} maxZoom={12} />
          {weather !== "none" ? <WeatherGridLayer bbox={padBBox(zoneToBBox(zone), 1.15)} time={targetIso} layer={weather as GridLayer} altitude={windAlt} onLoaded={onGridLoaded} /> : null}
          {overlays.airspaces && airspaces.data ? <AirspacesLayer features={airspaces.data.features} /> : null}
          {overlays.sensitive && sensitive.data ? <SensitiveAreasLayer features={sensitive.data.features} /> : null}
          <ZoneEditor zone={zone} onChange={setZone} mode={drawMode} onModeDone={() => setDrawMode("none")} />
          {plans.map((p) => (
            <RouteLayer key={p.id} plan={p} dim={hovered !== null && hovered !== p.id} highlight={hovered === p.id} />
          ))}
          {overlays.sites && sites.data ? <SiteMarkers sites={sites.data.sites} highlightIds={highlightIds} /> : null}
          {overlays.beacons && beacons.data ? <BeaconMarkers beacons={beacons.data.beacons} level={criteria.difficulty} now={now} /> : null}
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
        </div>
        <div className="planner__scroll" ref={resultsRef}>
          {tab === "criteria" || !results ? (
            <CriteriaPanel criteria={criteria} setCriteria={setCriteria} zone={zone} onZone={setZone} now={now} />
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
