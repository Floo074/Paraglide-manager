import { useCallback, useMemo, useState } from "react";
import type L from "leaflet";
import { getAirspaces, getSensitiveAreas } from "../../api/client";
import type { Beacon, Difficulty, FlightPlan, ForecastGridResponse, GridLayer } from "../../api/types";
import { BASE_LAYERS, DEFAULT_BASE_LAYER, KK7, type BaseLayerId } from "../../config/map";
import { useAsync } from "../../hooks/useAsync";
import { usePersistentState } from "../../hooks/usePersistentState";
import { formatTime } from "../../utils/format";
import { bboxFromCorners, padBBox } from "../../utils/zone";
import { AirspacesLayer, SensitiveAreasLayer } from "../map/AreaLayers";
import { BeaconMarkers } from "../map/BeaconMarkers";
import { FitTo, InvalidateOnResize } from "../map/FitTo";
import { LayersMenu, ZoomButtons } from "../map/MapControls";
import { MapShell } from "../map/MapShell";
import { LandingCandidateMarkers } from "../map/LandingLayers";
import { GlideRangeLayer, RouteLayer, WaypointMarkers } from "../map/PlanLayers";
import { PioupiouAttribution, StationReadingsLayer } from "../map/StationLayers";
import { hasPioupiou } from "../../utils/beacons";
import { GridLegend, WeatherGridLayer } from "../map/WeatherGrid";
import { WEATHER_LAYERS, WIND_ALTITUDE_OPTIONS, type WeatherLayerChoice } from "../map/weatherLayers";
import { ALTITUDE_STOPS, interpolateStops } from "../../utils/colors";
import { formatNumber } from "../../utils/format";

interface Overlays {
  airspaces: boolean;
  sensitive: boolean;
  beacons: boolean;
  glide: boolean;
  kk7: boolean;
  /** Atterros candidats de l'analyse (absent des préférences mémorisées avant cette option). */
  candidates?: boolean;
}
const DEFAULTS: Overlays = { airspaces: true, sensitive: true, beacons: true, glide: true, kk7: false, candidates: true };
const isBase = (v: unknown): v is BaseLayerId => BASE_LAYERS.some((b) => b.id === v);
const isOverlays = (v: unknown): v is Overlays => !!v && typeof v === "object" && "glide" in (v as object);

/** Bloc 5 : carte du vol avec couches météo commutables et curseur temporel. */
export function PlanMap({ plan, level, now }: { plan: FlightPlan; level: Difficulty; now: Date }) {
  const [map, setMap] = useState<L.Map | null>(null);
  const [baseLayer, setBaseLayer] = usePersistentState<BaseLayerId>("pm.baseLayer", DEFAULT_BASE_LAYER, isBase);
  const [ov, setOv] = usePersistentState<Overlays>("pm.overlays.plan", DEFAULTS, isOverlays);
  const [weather, setWeather] = useState<WeatherLayerChoice>("none");
  const [windAlt, setWindAlt] = useState(10);
  const [grid, setGrid] = useState<ForecastGridResponse | null>(null);
  const [gridLoading, setGridLoading] = useState(false);

  const times = useMemo(() => {
    const t = plan.weather.timeline.map((w) => w.time);
    return t.length ? t : [plan.target_time];
  }, [plan]);
  const targetIdx = Math.max(
    0,
    times.findIndex((t) => Math.abs(new Date(t).getTime() - new Date(plan.target_time).getTime()) < 31 * 60_000),
  );
  const [timeIdx, setTimeIdx] = useState(targetIdx);
  const time = times[Math.min(timeIdx, times.length - 1)]!;

  const routeBox = useMemo(() => {
    const pts = [...plan.route.coordinates.map((c) => ({ lat: c[1], lon: c[0] })), plan.landing, ...plan.alternate_landings, plan.takeoff];
    const lats = pts.map((p) => p.lat);
    const lons = pts.map((p) => p.lon);
    const b = bboxFromCorners({ lat: Math.min(...lats), lon: Math.min(...lons) }, { lat: Math.max(...lats), lon: Math.max(...lons) });
    return b;
  }, [plan]);
  const area = useMemo(() => {
    const b = padBBox(routeBox, 1.8);
    const minSide = 0.18;
    const cy = (b.min_lat + b.max_lat) / 2;
    const cx = (b.min_lon + b.max_lon) / 2;
    const h = Math.max(minSide, b.max_lat - b.min_lat) / 2;
    const w = Math.max(minSide * 1.4, b.max_lon - b.min_lon) / 2;
    return bboxFromCorners({ lat: cy - h, lon: cx - w }, { lat: cy + h, lon: cx + w });
  }, [routeBox]);
  const areaKey = `${area.min_lat},${area.min_lon},${area.max_lat},${area.max_lon}`;
  const airspaces = useAsync((s) => getAirspaces(area, s), [areaKey], ov.airspaces);
  const sensitive = useAsync((s) => getSensitiveAreas(area, plan.target_time, s), [areaKey, plan.target_time], ov.sensitive);
  const onGrid = useCallback((g: ForecastGridResponse | null, loading: boolean) => {
    setGrid(g);
    setGridLoading(loading);
  }, []);

  // balises proches + balises rattachées au plan (sans doublon)
  const beacons = useMemo(() => {
    const m = new Map<string, Beacon>();
    for (const b of plan.beacons_nearby) m.set(b.id, b);
    for (const r of plan.station_readings) if (!m.has(r.beacon.id)) m.set(r.beacon.id, r.beacon);
    return [...m.values()];
  }, [plan]);
  const showCandidates = ov.candidates !== false;
  const drawnLandings = useMemo(() => new Set([plan.landing.id, ...plan.alternate_landings.map((s) => s.id)]), [plan]);

  const alts = plan.route.coordinates.map((c) => c[2]);
  const minAlt = Math.min(...alts);
  const maxAlt = Math.max(...alts);

  return (
    <section className="block block--map" aria-labelledby="b-map">
      <h2 id="b-map" className="block__title">
        Carte du vol
      </h2>
      <MapShell
        ref={setMap}
        center={[plan.takeoff.lat, plan.takeoff.lon]}
        zoom={12}
        baseLayer={baseLayer}
        showKk7={ov.kk7}
        className="plan-map"
        ariaLabel="Carte du plan de vol"
        overlay={
          <>
            <div className="map-overlay map-overlay--tr">
              <LayersMenu
                baseLayer={baseLayer}
                onBaseLayer={setBaseLayer}
                overlays={[
                  { id: "glide", label: "Rayons de plané et vent sur le plané", checked: ov.glide, onChange: (v) => setOv({ ...ov, glide: v }) },
                  { id: "airspaces", label: "Espaces aériens", checked: ov.airspaces, onChange: (v) => setOv({ ...ov, airspaces: v }) },
                  { id: "sensitive", label: "Zones sensibles (faune, parcs)", checked: ov.sensitive, onChange: (v) => setOv({ ...ov, sensitive: v }) },
                  { id: "beacons", label: "Balises (celles du plan entourées)", checked: ov.beacons, onChange: (v) => setOv({ ...ov, beacons: v }) },
                  {
                    id: "candidates",
                    label: "Autres atterros évalués",
                    checked: showCandidates,
                    disabled: plan.landing_analysis.length <= 1,
                    onChange: (v) => setOv({ ...ov, candidates: v }),
                  },
                  {
                    id: "kk7",
                    label: "Hotspots thermiques KK7",
                    checked: ov.kk7 && !!KK7.url,
                    disabled: !KK7.url,
                    hint: KK7.url ? undefined : "Renseigner VITE_KK7_TILES_URL pour l'activer",
                    onChange: (v) => setOv({ ...ov, kk7: v }),
                  },
                ]}
              />
              <ZoomButtons map={map} />
            </div>
            <div className="map-overlay map-overlay--bl">
              <div className="alt-legend" aria-label="Couleur de la route selon l'altitude">
                <span className="num">{formatNumber(minAlt)} m</span>
                <span
                  className="alt-legend__bar"
                  style={{ background: `linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1].map((t) => interpolateStops(ALTITUDE_STOPS, t)).join(", ")})` }}
                />
                <span className="num">{formatNumber(maxAlt)} m</span>
              </div>
            </div>
          </>
        }
      >
        <InvalidateOnResize />
        <FitTo
          bounds={[
            [routeBox.min_lat, routeBox.min_lon],
            [routeBox.max_lat, routeBox.max_lon],
          ]}
          fitKey={plan.id}
          padding={36}
          maxZoom={14}
        />
        {weather !== "none" ? <WeatherGridLayer bbox={area} time={time} layer={weather as GridLayer} altitude={windAlt} onLoaded={onGrid} /> : null}
        {ov.airspaces && airspaces.data ? <AirspacesLayer features={airspaces.data.features} /> : null}
        {ov.sensitive && sensitive.data ? <SensitiveAreasLayer features={sensitive.data.features} /> : null}
        {ov.glide ? <GlideRangeLayer plan={plan} /> : null}
        <RouteLayer plan={plan} />
        <WaypointMarkers plan={plan} />
        {showCandidates ? <LandingCandidateMarkers candidates={plan.landing_analysis} skipIds={drawnLandings} /> : null}
        {ov.beacons ? <StationReadingsLayer plan={plan} /> : null}
        {ov.beacons ? <BeaconMarkers beacons={beacons} level={level} now={now} /> : null}
        <PioupiouAttribution active={ov.beacons && hasPioupiou(beacons)} />
      </MapShell>
      <div className="wx-controls">
        <label className="field-row">
          <span>Météo</span>
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
        {weather !== "none" && times.length > 1 ? (
          <label className="field-row field-row--grow">
            <span className="nowrap">
              Heure <strong className="num">{formatTime(time)}</strong>
              {timeIdx === targetIdx ? <span className="faint small"> (cible)</span> : null}
            </span>
            <input type="range" className="range" min={0} max={times.length - 1} step={1} value={timeIdx} onChange={(e) => setTimeIdx(Number(e.target.value))} aria-valuetext={formatTime(time)} />
          </label>
        ) : null}
        {gridLoading ? <span className="small faint">chargement…</span> : null}
      </div>
      {weather !== "none" ? <GridLegend layer={weather as GridLayer} grid={grid} /> : null}
    </section>
  );
}
