import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";

/** Recadre la carte quand `fitKey` change (ex. nouvelle zone choisie). */
export function FitTo({
  bounds,
  fitKey,
  padding = 24,
  maxZoom = 13,
  animate = true,
  bottomInset = 0,
}: {
  bounds: L.LatLngBoundsExpression | null;
  fitKey: string;
  padding?: number;
  maxZoom?: number;
  animate?: boolean;
  /** Hauteur (px) masquée en bas de la carte (panneau mobile) à exclure du cadrage. */
  bottomInset?: number;
}) {
  const map = useMap();
  const last = useRef<string | null>(null);
  useEffect(() => {
    if (!bounds || last.current === fitKey) return;
    const first = last.current === null;
    last.current = fitKey;
    const b = L.latLngBounds(bounds as L.LatLngBoundsLiteral);
    if (!b.isValid()) return;
    map.invalidateSize();
    const opts = { paddingTopLeft: L.point(padding, padding), paddingBottomRight: L.point(padding, padding + bottomInset), maxZoom };
    if (first || !animate) map.fitBounds(b, { ...opts, animate: false });
    else map.flyToBounds(b, { ...opts, duration: 0.8 });
  }, [bounds, fitKey, map, padding, maxZoom, animate, bottomInset]);
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
