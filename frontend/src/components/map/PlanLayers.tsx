import { Fragment, useMemo } from "react";
import { Circle, Marker, Polyline, Popup, Tooltip } from "react-leaflet";
import type { FlightPlan, Site } from "../../api/types";
import { altitudeColor } from "../../utils/colors";
import { waypointTypeLabel } from "../../utils/exports";
import { formatAltitude, formatNumber, formatTime } from "../../utils/format";
import { waypointIcon } from "./icons";

/** Route 3D colorée par altitude (segments), avec liseré pour la lisibilité sur le relief. */
export function RouteLayer({ plan, dim = false, highlight = false, onClick }: { plan: FlightPlan; dim?: boolean; highlight?: boolean; onClick?: () => void }) {
  const coords = plan.route.coordinates;
  const { min, max } = useMemo(() => {
    const alts = coords.map((c) => c[2]);
    return { min: Math.min(...alts), max: Math.max(...alts) };
  }, [coords]);
  const latlngs = coords.map((c) => [c[1], c[0]] as [number, number]);
  if (coords.length < 2) return null;
  const weight = highlight ? 6 : dim ? 3 : 5;
  return (
    <>
      <Polyline positions={latlngs} pathOptions={{ color: "#ffffff", weight: weight + 5, opacity: dim ? 0.35 : 0.9, lineCap: "round", lineJoin: "round" }} eventHandlers={onClick ? { click: onClick } : undefined} />
      <Polyline positions={latlngs} pathOptions={{ color: "#0b1220", weight: weight + 2, opacity: dim ? 0.3 : 0.7, lineCap: "round", lineJoin: "round" }} interactive={false} />
      {coords.slice(1).map((c, i) => {
        const a = coords[i]!;
        const alt = (a[2] + c[2]) / 2;
        return (
          <Polyline
            key={i}
            positions={[
              [a[1], a[0]],
              [c[1], c[0]],
            ]}
            pathOptions={{ color: altitudeColor(alt, min, max), weight, opacity: dim ? 0.45 : 1, lineCap: "round" }}
            eventHandlers={onClick ? { click: onClick } : undefined}
          />
        );
      })}
    </>
  );
}

/** Waypoints avec ETA en heure légale et altitude ; cylindres de validation des balises. */
export function WaypointMarkers({ plan }: { plan: FlightPlan }) {
  const start = new Date(plan.window.start).getTime();
  let n = 0;
  return (
    <>
      {plan.waypoints.map((w, i) => {
        if (w.type === "turnpoint") n += 1;
        const eta = w.eta_min !== null ? new Date(start + w.eta_min * 60_000) : null;
        return (
          <Fragment key={`${w.name}-${i}`}>
            {w.type === "turnpoint" && w.radius_m ? (
              <Circle center={[w.lat, w.lon]} radius={w.radius_m} pathOptions={{ color: "#7c3aed", weight: 1.5, dashArray: "4 4", fillOpacity: 0.05 }} interactive={false} />
            ) : null}
            <Marker position={[w.lat, w.lon]} icon={waypointIcon(w.type, n)} zIndexOffset={w.type === "landing" ? 900 : w.type === "takeoff" ? 950 : 700} title={w.name}>
              <Tooltip direction="top" offset={[0, -12]} className="wp-tooltip">
                {w.name}
                {eta ? ` · ${formatTime(eta)}` : ""} · {formatAltitude(w.altitude_m)}
              </Tooltip>
              <Popup>
                <div className="popup">
                  <div className="popup__title">{w.name}</div>
                  <div className="popup__meta">{waypointTypeLabel(w.type)}</div>
                  <div>
                    <span className="muted">Altitude :</span> {formatAltitude(w.altitude_m)}
                  </div>
                  {eta ? (
                    <div>
                      <span className="muted">Passage estimé :</span> {formatTime(eta)} (+{w.eta_min} min, si déco à {formatTime(plan.window.start)})
                    </div>
                  ) : null}
                  {w.radius_m ? (
                    <div>
                      <span className="muted">Rayon :</span> {formatNumber(w.radius_m)} m
                    </div>
                  ) : null}
                  {w.note ? <p className="popup__text">{w.note}</p> : null}
                  <div className="popup__foot mono">
                    {w.lat.toFixed(5)}, {w.lon.toFixed(5)}
                  </div>
                </div>
              </Popup>
            </Marker>
          </Fragment>
        );
      })}
    </>
  );
}

/**
 * Rayons de plané autour des atterrissages : distance atteignable depuis l'altitude du déco
 * et depuis l'altitude max du vol, avec la finesse de calcul sol du plan (glide.available_ratio).
 */
export function GlideRangeLayer({ plan }: { plan: FlightPlan }) {
  const ratio = plan.glide.available_ratio;
  if (!(ratio > 0)) return null;
  const landings: { site: Site; main: boolean }[] = [
    { site: plan.landing, main: true },
    ...plan.alternate_landings.map((s) => ({ site: s, main: false })),
  ];
  const fromAlts = [plan.takeoff.elevation_m, plan.max_altitude_m].filter((v, i, a) => a.indexOf(v) === i);
  return (
    <>
      {landings.map(({ site, main }) =>
        fromAlts.map((alt, j) => {
          const h = alt - site.elevation_m;
          if (h <= 0) return null;
          const r = (h * ratio) / 1000;
          return (
            <Circle
              key={`${site.id}-${j}`}
              center={[site.lat, site.lon]}
              radius={r * 1000}
              pathOptions={{
                color: main ? "#16a34a" : "#64748b",
                weight: main ? 2 : 1.2,
                dashArray: j === 0 ? "2 6" : "10 6",
                fillOpacity: main && j === 0 ? 0.05 : 0,
                className: "glide-ring",
              }}
              interactive
            >
              <Tooltip sticky>
                {site.name} : atteignable à {formatNumber(r, 1)} km depuis {formatAltitude(alt)} (finesse de calcul {formatNumber(ratio, 1)})
              </Tooltip>
            </Circle>
          );
        }),
      )}
      <Polyline
        positions={[
          [plan.takeoff.lat, plan.takeoff.lon],
          [plan.landing.lat, plan.landing.lon],
        ]}
        pathOptions={{ color: "#16a34a", weight: 1.5, dashArray: "3 6", opacity: 0.9 }}
      >
        <Tooltip sticky>
          Plané déco → {plan.landing.name} : finesse requise {formatNumber(plan.glide.required_ratio, 1)} / disponible{" "}
          {formatNumber(plan.glide.available_ratio, 1)}
        </Tooltip>
      </Polyline>
    </>
  );
}
