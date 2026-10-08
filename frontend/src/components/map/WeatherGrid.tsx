import { useEffect } from "react";
import { Marker, Rectangle, Tooltip } from "react-leaflet";
import L from "leaflet";
import { getForecastGrid } from "../../api/client";
import type { BBoxZone, ForecastGridResponse, GridLayer } from "../../api/types";
import { useAsync } from "../../hooks/useAsync";
import { WIND_STOPS, interpolateStops } from "../../utils/colors";
import { WEATHER_LAYERS } from "./weatherLayers";
import { formatNumber, formatTime } from "../../utils/format";
import { degToCardinalFr } from "../../utils/units";
import { bboxParam } from "../../utils/zone";
import { useMapZoom } from "./useMapZoom";
import { windArrowIcon } from "./icons";

const canvas = L.canvas({ padding: 0.3 });

/** Couche de grille météo (/api/forecast/grid). */
export function WeatherGridLayer({
  bbox,
  time,
  layer,
  altitude,
  onLoaded,
}: {
  bbox: BBoxZone;
  time: string;
  layer: GridLayer;
  altitude: number;
  onLoaded?: (g: ForecastGridResponse | null, loading: boolean, error: Error | null) => void;
}) {
  const key = `${bboxParam(bbox)}|${time}|${layer}|${altitude}`;
  const { data, loading, error } = useAsync((signal) => getForecastGrid(bbox, time, layer, altitude, signal), [key]);
  const zoom = useMapZoom();
  useEffect(() => onLoaded?.(data, loading, error), [data, loading, error, onLoaded]);
  if (!data || data.layer !== layer) return null;
  const def = WEATHER_LAYERS.find((l) => l.value === layer)!;
  const half = data.resolution_deg / 2;
  if (layer === "wind") {
    return (
      <>
        {data.points.map((p, i) =>
          p.direction_deg === null ? null : (
            <Marker
              key={i}
              position={[p.lat, p.lon]}
              icon={windArrowIcon(p.value, p.direction_deg, interpolateStops(WIND_STOPS, p.value), zoom >= 13)}
              interactive
              keyboard={false}
              zIndexOffset={-100}
            >
              <Tooltip direction="top" offset={[0, -10]}>
                Vent de {degToCardinalFr(p.direction_deg)} · {Math.round(p.value)} km/h
                {data.altitude_m && data.altitude_m > 10 ? ` à ${formatNumber(data.altitude_m)} m` : " au sol"}
              </Tooltip>
            </Marker>
          ),
        )}
      </>
    );
  }
  return (
    <>
      {data.points.map((p, i) => {
        if (layer === "precipitation" && p.value < 0.05) return null;
        return (
          <Rectangle
            key={i}
            bounds={[
              [p.lat - half, p.lon - half],
              [p.lat + half, p.lon + half],
            ]}
            pathOptions={{ renderer: canvas, stroke: false, fillColor: interpolateStops(def.stops!, p.value), fillOpacity: 0.42 }}
            interactive={false}
          />
        );
      })}
    </>
  );
}

/** Légende : dégradé de la palette + étendue des valeurs de la grille. */
export function GridLegend({ layer, grid }: { layer: GridLayer; grid: ForecastGridResponse | null }) {
  const def = WEATHER_LAYERS.find((l) => l.value === layer)!;
  const stops = def.stops!;
  const gradient = `linear-gradient(to right, ${stops.map((s, i) => `${interpolateStops(stops, s.value)} ${(i / (stops.length - 1)) * 100}%`).join(", ")})`;
  const digits = layer === "thermal" || layer === "precipitation" ? 1 : 0;
  return (
    <div className="grid-legend">
      {layer === "wind" ? (
        <div className="grid-legend__big">
          {grid?.altitude_m && grid.altitude_m > 10 ? `Vent à ${formatNumber(grid.altitude_m)} m` : "Vent au sol (10 m)"}
        </div>
      ) : null}
      <div className="grid-legend__title">
        {layer === "wind" ? "Vitesse" : def.label}
        <span className="muted"> ({def.unit})</span>
      </div>
      <div className="grid-legend__bar" style={{ background: gradient }} />
      <div className="grid-legend__ticks">
        {stops.map((s) => (
          <span key={s.value}>{formatNumber(s.value, digits)}</span>
        ))}
      </div>
      {grid ? (
        <div className="grid-legend__range muted">
          Zone : {formatNumber(grid.legend.min, digits)} – {formatNumber(grid.legend.max, digits)} {grid.unit} · {formatTime(grid.time)}
          {layer === "cloudbase" && grid.points.length === 0 ? " · aucun cumulus" : ""}
        </div>
      ) : null}
      {def.hint ? <div className="grid-legend__hint">{def.hint}</div> : null}
    </div>
  );
}
