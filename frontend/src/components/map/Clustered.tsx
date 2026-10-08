import { useMemo, useState, type ReactNode } from "react";
import { Marker, useMap, useMapEvents } from "react-leaflet";
import { clusterIcon } from "./icons";

/** Zoom courant de la carte (mis à jour en fin de zoom). */
export function useMapZoom(): number {
  const map = useMap();
  const [zoom, setZoom] = useState(map.getZoom());
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) });
  return zoom;
}

/**
 * Regroupement simple par grille de pixels : au-delà de `maxClusterZoom`, tous les marqueurs
 * sont affichés ; en dessous, les marqueurs proches (< `cell` px) forment une bulle cliquable.
 */
export function Clustered<T>({
  items,
  getId,
  getLatLng,
  render,
  kind,
  cell = 54,
  maxClusterZoom = 11,
}: {
  items: T[];
  getId: (t: T) => string;
  getLatLng: (t: T) => [number, number];
  render: (t: T) => ReactNode;
  kind: "site" | "beacon";
  cell?: number;
  maxClusterZoom?: number;
}) {
  const map = useMap();
  const zoom = useMapZoom();
  const groups = useMemo(() => {
    if (zoom > maxClusterZoom) return items.map((t) => [t]);
    const cells = new Map<string, T[]>();
    for (const t of items) {
      const p = map.project(getLatLng(t), zoom);
      const key = `${Math.floor(p.x / cell)}:${Math.floor(p.y / cell)}`;
      const list = cells.get(key);
      if (list) list.push(t);
      else cells.set(key, [t]);
    }
    return Array.from(cells.values());
  }, [items, zoom, map, cell, maxClusterZoom, getLatLng]);

  return (
    <>
      {groups.map((g) => {
        if (g.length === 1) return <Fragmentless key={getId(g[0]!)}>{render(g[0]!)}</Fragmentless>;
        const lat = g.reduce((s, t) => s + getLatLng(t)[0], 0) / g.length;
        const lon = g.reduce((s, t) => s + getLatLng(t)[1], 0) / g.length;
        return (
          <Marker
            key={`c-${getId(g[0]!)}-${g.length}`}
            position={[lat, lon]}
            icon={clusterIcon(g.length, kind)}
            title={`${g.length} ${kind === "site" ? "sites" : "balises"} — cliquer pour zoomer`}
            eventHandlers={{ click: () => map.flyTo([lat, lon], Math.min(map.getMaxZoom(), zoom + 2)) }}
          />
        );
      })}
    </>
  );
}

function Fragmentless({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
