import { useEffect, useMemo } from "react";
import { Marker, Polygon, Popup, Tooltip, useMap, useMapEvents } from "react-leaflet";
import type L from "leaflet";
import type { GeoJsonPolygon, LandingCandidate } from "../../api/types";
import { LANDING_KIND } from "../../config/labels";
import { formatAltitude, formatNumber } from "../../utils/format";
import { compassFr } from "../../utils/units";
import type { FreeTakeoff } from "../planner/criteria";
import { freeTakeoffIcon, landingCandidateIcon } from "./icons";

/** Cône de finesse (zone atteignable avec marge, vent compris) renvoyé par l'analyse. */
export function GlideConeLayer({ cone, stale = false }: { cone: GeoJsonPolygon; stale?: boolean }) {
  const rings = useMemo(() => cone.coordinates.map((ring) => ring.map((c) => [c[1], c[0]] as [number, number])), [cone]);
  if (!rings.length || rings[0]!.length < 3) return null;
  return (
    <Polygon
      positions={rings}
      pathOptions={{ color: "#7c3aed", weight: 2, dashArray: "6 5", fillColor: "#7c3aed", fillOpacity: stale ? 0.03 : 0.08, opacity: stale ? 0.45 : 0.9, className: "glide-cone" }}
    >
      <Tooltip sticky>Cône de finesse : zone atteignable avec marge, vent compris{stale ? " (déco déplacé : relancer l'analyse)" : ""}</Tooltip>
    </Polygon>
  );
}

/** Atterros candidats colorés par catégorie, numérotés comme dans la liste. */
export function LandingCandidateMarkers({
  candidates,
  selectedId,
  onSelect,
  skipIds,
}: {
  candidates: LandingCandidate[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  /** Sites déjà dessinés autrement (atterro principal / secours d'un plan). */
  skipIds?: Set<string>;
}) {
  return (
    <>
      {candidates.map((c, i) => {
        if (skipIds?.has(c.site.id)) return null;
        const sel = selectedId === c.site.id;
        const k = LANDING_KIND[c.kind];
        // au-dessus des balises (800), sous le déco libre (1200) et les points du plan (900+)
        return (
          <Marker
            key={c.site.id}
            position={[c.site.lat, c.site.lon]}
            icon={landingCandidateIcon(c.kind, i + 1, sel)}
            zIndexOffset={sel ? 1100 : 860 - i}
            title={`${i + 1}. ${c.site.name}`}
            alt={`Atterrissage candidat ${i + 1} : ${c.site.name} (${k.label})`}
            eventHandlers={onSelect ? { click: () => onSelect(c.site.id) } : undefined}
          >
            <Tooltip direction="top" offset={[0, -12]}>
              {i + 1}. {c.site.name} · {k.label} · {Math.round(c.score)}/100
            </Tooltip>
            {onSelect ? null : (
              <Popup>
                <div className="popup">
                  <div className="popup__title">{c.site.name}</div>
                  <div className="popup__meta">
                    {k.label} · {formatAltitude(c.site.elevation_m)} · score {Math.round(c.score)}/100
                  </div>
                  <div>
                    <span className="muted">Finesse :</span> requise {formatNumber(c.required_glide_ratio, 1)} / disponible {formatNumber(c.available_glide_ratio, 1)}
                  </div>
                  <div>
                    <span className="muted">Arrivée :</span> {formatNumber(Math.round(c.arrival_height_m))} m au-dessus
                  </div>
                  {c.warnings.length ? <p className="popup__warn">{c.warnings[0]}</p> : null}
                </div>
              </Popup>
            )}
          </Marker>
        );
      })}
    </>
  );
}

/** Marqueur du décollage libre, déplaçable. */
export function FreeTakeoffMarker({ takeoff, onMove }: { takeoff: FreeTakeoff; onMove: (lat: number, lon: number) => void }) {
  const icon = useMemo(() => freeTakeoffIcon(takeoff.orientations), [takeoff.orientations]);
  return (
    <Marker
      position={[takeoff.lat, takeoff.lon]}
      icon={icon}
      draggable
      zIndexOffset={1200}
      title="Décollage libre (déplaçable)"
      alt="Décollage libre"
      eventHandlers={{
        dragend: (e) => {
          const ll = (e.target as L.Marker).getLatLng();
          onMove(ll.lat, ll.lng);
        },
      }}
    >
      <Tooltip direction="top" offset={[0, -22]}>
        {takeoff.name.trim() || "Décollage libre"}
        {takeoff.elevation !== null ? ` · ${formatAltitude(takeoff.elevation)}` : ""}
        {takeoff.orientations.length ? ` · ${takeoff.orientations.map(compassFr).join(", ")}` : ""} — glisser pour déplacer
      </Tooltip>
    </Marker>
  );
}

/** Clic sur la carte → point de décollage (curseur en croix pendant la sélection). */
export function MapPointPicker({ active, onPick }: { active: boolean; onPick: (lat: number, lon: number) => void }) {
  const map = useMap();
  useEffect(() => {
    const el = map.getContainer();
    el.classList.toggle("map--drawing", active);
    return () => el.classList.remove("map--drawing");
  }, [active, map]);
  useMapEvents({
    click(e) {
      if (active) onPick(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}
