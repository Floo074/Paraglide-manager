import { useEffect, useState } from "react";
import { Circle, Marker, Rectangle, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import type { Zone } from "../../api/types";
import { destinationPoint, haversineKm } from "../../utils/geo";
import { MAX_RADIUS_KM, MIN_RADIUS_KM, bboxFromCorners, validateZone } from "../../utils/zone";
import { handleIcon } from "./icons";

export type DrawMode = "none" | "rect" | "circle";

const ZONE_STYLE = { color: "#0ea5e9", weight: 2.5, dashArray: "8 6", fillColor: "#0ea5e9", fillOpacity: 0.06 };
const ZONE_STYLE_ERR = { ...ZONE_STYLE, color: "#ef4444", fillColor: "#ef4444" };

/**
 * Affiche la zone de recherche et permet de la dessiner :
 *  - rectangle : deux appuis (coins opposés), aperçu en suivant le pointeur ;
 *  - cercle : un appui place le centre ; poignées pour déplacer le centre et ajuster le rayon.
 */
export function ZoneEditor({
  zone,
  onChange,
  mode,
  onModeDone,
}: {
  zone: Zone;
  onChange: (z: Zone) => void;
  mode: DrawMode;
  onModeDone: () => void;
}) {
  const map = useMap();
  const [corner, setCorner] = useState<L.LatLng | null>(null);
  const [hover, setHover] = useState<L.LatLng | null>(null);

  useEffect(() => {
    const el = map.getContainer();
    el.classList.toggle("map--drawing", mode !== "none");
    if (mode === "none") {
      setCorner(null);
      setHover(null);
    }
    return () => el.classList.remove("map--drawing");
  }, [mode, map]);

  useMapEvents({
    click(e) {
      if (mode === "circle") {
        const r = zone.type === "circle" ? zone.radius_km : 20;
        onChange({ type: "circle", center: { lat: e.latlng.lat, lon: e.latlng.lng }, radius_km: r });
        onModeDone();
      } else if (mode === "rect") {
        if (!corner) setCorner(e.latlng);
        else {
          const z = bboxFromCorners({ lat: corner.lat, lon: corner.lng }, { lat: e.latlng.lat, lon: e.latlng.lng });
          setCorner(null);
          if (z.max_lat - z.min_lat > 0.005 && z.max_lon - z.min_lon > 0.005) onChange(z);
          onModeDone();
        }
      }
    },
    mousemove(e) {
      if (mode === "rect" && corner) setHover(e.latlng);
    },
  });

  const invalid = validateZone(zone) !== null;
  const style = invalid ? ZONE_STYLE_ERR : ZONE_STYLE;

  return (
    <>
      {zone.type === "circle" ? (
        <>
          <Circle center={[zone.center.lat, zone.center.lon]} radius={zone.radius_km * 1000} pathOptions={style} interactive={false} />
          {mode === "none" ? (
            <>
              <Marker
                position={[zone.center.lat, zone.center.lon]}
                icon={handleIcon("center")}
                draggable
                title="Déplacer le centre de la zone"
                keyboard={false}
                eventHandlers={{
                  dragend: (e) => {
                    const ll = (e.target as L.Marker).getLatLng();
                    onChange({ ...zone, center: { lat: ll.lat, lon: ll.lng } });
                  },
                }}
              />
              <RadiusHandle zone={zone} onChange={onChange} />
            </>
          ) : null}
        </>
      ) : (
        <Rectangle
          bounds={[
            [zone.min_lat, zone.min_lon],
            [zone.max_lat, zone.max_lon],
          ]}
          pathOptions={style}
          interactive={false}
        />
      )}
      {mode === "rect" && corner ? (
        <>
          <Marker position={corner} icon={handleIcon("center")} interactive={false} />
          {hover ? <Rectangle bounds={L.latLngBounds(corner, hover)} pathOptions={{ ...ZONE_STYLE, dashArray: "4 4" }} interactive={false} /> : null}
        </>
      ) : null}
    </>
  );
}

function RadiusHandle({ zone, onChange }: { zone: Extract<Zone, { type: "circle" }>; onChange: (z: Zone) => void }) {
  const p = destinationPoint(zone.center, 90, zone.radius_km);
  return (
    <Marker
      position={[p.lat, p.lon]}
      icon={handleIcon("radius")}
      draggable
      keyboard={false}
      title="Ajuster le rayon"
      eventHandlers={{
        dragend: (e) => {
          const ll = (e.target as L.Marker).getLatLng();
          const r = haversineKm(zone.center, { lat: ll.lat, lon: ll.lng });
          onChange({ ...zone, radius_km: Math.round(Math.min(MAX_RADIUS_KM, Math.max(MIN_RADIUS_KM, r))) });
        },
      }}
    />
  );
}
