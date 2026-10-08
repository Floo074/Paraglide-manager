import { useState } from "react";
import { useMap, useMapEvents } from "react-leaflet";

/** Zoom courant de la carte (mis à jour en fin de zoom). */
export function useMapZoom(): number {
  const map = useMap();
  const [zoom, setZoom] = useState(map.getZoom());
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) });
  return zoom;
}

