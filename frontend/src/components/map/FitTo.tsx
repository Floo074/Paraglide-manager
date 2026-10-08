import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";

/** Recadre la carte quand `fitKey` change (ex. nouvelle zone choisie). */
export function FitTo({ bounds, fitKey, padding = 24, maxZoom = 13, animate = true }: { bounds: L.LatLngBoundsExpression | null; fitKey: string; padding?: number; maxZoom?: number; animate?: boolean }) {
  const map = useMap();
  const last = useRef<string | null>(null);
  useEffect(() => {
    if (!bounds || last.current === fitKey) return;
    const first = last.current === null;
    last.current = fitKey;
    const b = L.latLngBounds(bounds as L.LatLngBoundsLiteral);
    if (!b.isValid()) return;
    map.invalidateSize();
    if (first || !animate) map.fitBounds(b, { padding: [padding, padding], maxZoom, animate: false });
    else map.flyToBounds(b, { padding: [padding, padding], maxZoom, duration: 0.8 });
  }, [bounds, fitKey, map, padding, maxZoom, animate]);
  return null;
}

/** Recalcule la taille de la carte quand son conteneur change (panneau, bottom sheet). */
export function InvalidateOnResize() {
  const map = useMap();
  useEffect(() => {
    const el = map.getContainer();
    const ro = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [map]);
  return null;
}
