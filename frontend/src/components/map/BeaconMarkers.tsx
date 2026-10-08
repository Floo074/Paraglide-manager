import { useCallback } from "react";
import { Marker, Popup } from "react-leaflet";
import type { Beacon, Difficulty } from "../../api/types";
import { SOURCE_LABEL } from "../../config/labels";
import { beaconColor } from "../../config/thresholds";
import { formatAge, formatAltitude, formatNumber, formatSpeed, formatTime } from "../../utils/format";
import { degToCardinalFr } from "../../utils/units";
import { Clustered } from "./Clustered";
import { beaconIcon } from "./icons";

export function BeaconPopupContent({ b, now }: { b: Beacon; now: Date }) {
  return (
    <div className="popup">
      <div className="popup__title">{b.name}</div>
      <div className="popup__meta">
        Balise {SOURCE_LABEL[b.source] ?? b.source}
        {b.elevation_m !== null ? ` · ${formatAltitude(b.elevation_m)}` : ""}
      </div>
      <div>
        <span className="muted">Vent :</span>{" "}
        {b.wind_speed_kmh === null ? (
          "indisponible"
        ) : (
          <>
            {b.wind_direction_deg !== null ? `${degToCardinalFr(b.wind_direction_deg)} (${Math.round(b.wind_direction_deg)}°) ` : "variable "}
            {formatSpeed(b.wind_speed_kmh)}
            {b.wind_gust_kmh !== null ? `, rafales ${formatSpeed(b.wind_gust_kmh)}` : ""}
          </>
        )}
      </div>
      {b.temperature_c !== null ? (
        <div>
          <span className="muted">Température :</span> {formatNumber(b.temperature_c, 1)} °C
        </div>
      ) : null}
      <div>
        <span className="muted">Mesure :</span> {formatTime(b.observed_at)} ({formatAge(b.observed_at, now)})
      </div>
      {b.stale ? <p className="popup__warn">Mesure de plus de 30 min : à ne pas utiliser pour décider.</p> : null}
    </div>
  );
}

export function BeaconMarkers({ beacons, level, now }: { beacons: Beacon[]; level: Difficulty | null; now: Date }) {
  const getLatLng = useCallback((b: Beacon): [number, number] => [b.lat, b.lon], []);
  const getId = useCallback((b: Beacon) => b.id, []);
  return (
    <Clustered
      items={beacons}
      kind="beacon"
      getId={getId}
      getLatLng={getLatLng}
      maxClusterZoom={9}
      cell={46}
      render={(b) => (
        <Marker
          position={[b.lat, b.lon]}
          icon={beaconIcon(b, beaconColor(b.wind_speed_kmh, b.wind_gust_kmh, level), now)}
          zIndexOffset={800}
          title={b.name}
          alt={`Balise ${b.name}`}
        >
          <Popup>
            <BeaconPopupContent b={b} now={now} />
          </Popup>
        </Marker>
      )}
    />
  );
}
