import { forwardRef, type ReactNode } from "react";
import { MapContainer, TileLayer, ScaleControl } from "react-leaflet";
import type L from "leaflet";
import { BASE_LAYERS, DEFAULT_BASE_LAYER, KK7, type BaseLayerId } from "../../config/map";

export interface MapShellProps {
  center: [number, number];
  zoom: number;
  baseLayer: BaseLayerId;
  showKk7?: boolean;
  children?: ReactNode;
  /** Contrôles superposés (positionnés en CSS, hors Leaflet). */
  overlay?: ReactNode;
  className?: string;
  ariaLabel?: string;
}

/** Conteneur de carte : fond choisi (sans clé d'API), échelle, contrôles superposés. */
export const MapShell = forwardRef<L.Map, MapShellProps>(function MapShell(
  { center, zoom, baseLayer, showKk7 = false, children, overlay, className = "", ariaLabel = "Carte" },
  ref,
) {
  const base = BASE_LAYERS.find((b) => b.id === baseLayer) ?? BASE_LAYERS.find((b) => b.id === DEFAULT_BASE_LAYER)!;
  return (
    <div className={`map-shell ${className}`} role="region" aria-label={ariaLabel}>
      <MapContainer ref={ref} center={center} zoom={zoom} zoomControl={false} className="map" worldCopyJump attributionControl>
        <TileLayer
          key={base.id}
          url={base.url}
          attribution={base.attribution}
          maxZoom={base.maxZoom}
          maxNativeZoom={base.maxNativeZoom ?? base.maxZoom}
          subdomains={base.subdomains ?? "abc"}
          className="base-tiles"
          crossOrigin
        />
        {showKk7 && KK7.url ? (
          <TileLayer
            url={KK7.url}
            attribution={KK7.attribution}
            tms={KK7.tms}
            opacity={0.55}
            maxNativeZoom={KK7.maxNativeZoom}
            zIndex={5}
          />
        ) : null}
        <ScaleControl position="bottomleft" imperial={false} />
        {children}
      </MapContainer>
      {overlay}
    </div>
  );
});
