import { Fragment, useEffect } from "react";
import { CircleMarker, Polyline, Tooltip, useMap } from "react-leaflet";
import type { FlightPlan, Site, StationReading } from "../../api/types";
import { PIOUPIOU_ATTRIBUTION, STATION_ROLE_LABEL } from "../../utils/beacons";
import { formatNumber } from "../../utils/format";

const ROLE_COLOR: Record<StationReading["site_role"], string> = {
  takeoff: "#15803d",
  landing: "#1d4ed8",
  alternate_landing: "#64748b",
};

/**
 * Balises rattachées au plan : anneau autour de la balise et pointillé vers son site
 * (vert = déco, bleu = atterro, gris = secours ; pâle si la balise n'est qu'indicative).
 */
export function StationReadingsLayer({ plan }: { plan: FlightPlan }) {
  const sites = new Map<string, Site>([plan.takeoff, plan.landing, ...plan.alternate_landings].map((s) => [s.id, s]));
  for (const c of plan.landing_analysis) if (!sites.has(c.site.id)) sites.set(c.site.id, c.site);
  return (
    <>
      {plan.station_readings.map((r, i) => {
        const site = sites.get(r.site_id);
        const color = ROLE_COLOR[r.site_role];
        const b = r.beacon;
        const op = r.representative ? 1 : 0.45;
        return (
          <Fragment key={`${r.site_id}-${b.id}-${i}`}>
            {site ? (
              <Polyline
                positions={[
                  [b.lat, b.lon],
                  [site.lat, site.lon],
                ]}
                pathOptions={{ color, weight: 2, dashArray: "2 6", opacity: 0.85 * op, lineCap: "round" }}
                interactive={false}
              />
            ) : null}
            <CircleMarker
              center={[b.lat, b.lon]}
              radius={21}
              pathOptions={{ color, weight: r.representative ? 3 : 2, dashArray: r.representative ? undefined : "4 4", fill: false, opacity: op, className: "station-ring" }}
            >
              <Tooltip direction="right" offset={[18, 0]}>
                {b.name} → {STATION_ROLE_LABEL[r.site_role].toLowerCase()} {site ? site.name : ""} · {formatNumber(r.distance_km, 1)} km
                {r.representative ? " · représentative" : " · indicative"}
              </Tooltip>
            </CircleMarker>
          </Fragment>
        );
      })}
    </>
  );
}

/** Ajoute l'attribution OpenWindMap / Pioupiou à la carte tant que des balises Pioupiou sont affichées. */
export function PioupiouAttribution({ active }: { active: boolean }) {
  const map = useMap();
  useEffect(() => {
    const ctl = map.attributionControl;
    if (!active || !ctl) return;
    ctl.addAttribution(PIOUPIOU_ATTRIBUTION);
    return () => {
      ctl.removeAttribution(PIOUPIOU_ATTRIBUTION);
    };
  }, [active, map]);
  return null;
}
