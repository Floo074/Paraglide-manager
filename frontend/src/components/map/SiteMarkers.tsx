import { useCallback, useMemo } from "react";
import { Marker, Popup } from "react-leaflet";
import type { Site } from "../../api/types";
import { SITE_KIND_LABEL, SITE_STATUS_LABEL, SOURCE_LABEL, difficultyLabel, flightTypeLabel } from "../../config/labels";
import { formatAltitude } from "../../utils/format";
import { compassFr } from "../../utils/units";
import { Clustered } from "./Clustered";
import { landingIcon, takeoffIcon } from "./icons";

export function SitePopupContent({ site }: { site: Site }) {
  return (
    <div className="popup">
      <div className="popup__title">{site.name}</div>
      <div className="popup__meta">
        {SITE_KIND_LABEL[site.kind]} · {formatAltitude(site.elevation_m)}
        {site.status !== "open" ? <> · <strong>{SITE_STATUS_LABEL[site.status]}</strong></> : null}
      </div>
      {site.kind !== "landing" && site.orientations.length ? (
        <div>
          <span className="muted">Orientations :</span> {site.orientations.map(compassFr).join(", ")}
        </div>
      ) : null}
      {site.difficulty ? (
        <div>
          <span className="muted">Niveau conseillé :</span> {difficultyLabel(site.difficulty)}
        </div>
      ) : null}
      {site.flight_types.length ? (
        <div>
          <span className="muted">Vols :</span> {site.flight_types.map(flightTypeLabel).join(", ")}
        </div>
      ) : null}
      {site.description ? <p className="popup__text">{site.description}</p> : null}
      {site.access ? (
        <p className="popup__text">
          <span className="muted">Accès :</span> {site.access}
        </p>
      ) : null}
      {site.restrictions ? <p className="popup__warn">{site.restrictions}</p> : null}
      <div className="popup__foot">
        Source : {SOURCE_LABEL[site.source] ?? site.source}
        {site.url ? (
          <>
            {" · "}
            <a href={site.url} target="_blank" rel="noreferrer">
              fiche
            </a>
          </>
        ) : null}
      </div>
    </div>
  );
}

export function SiteMarkers({ sites, highlightIds }: { sites: Site[]; highlightIds?: Set<string> }) {
  const getLatLng = useCallback((s: Site): [number, number] => [s.lat, s.lon], []);
  const getId = useCallback((s: Site) => s.id, []);
  const sorted = useMemo(() => [...sites].sort((a, b) => (a.kind === "landing" ? -1 : 0) - (b.kind === "landing" ? -1 : 0)), [sites]);
  return (
    <Clustered
      items={sorted}
      kind="site"
      getId={getId}
      getLatLng={getLatLng}
      maxClusterZoom={10}
      render={(s) => {
        const hl = highlightIds?.has(s.id) ?? false;
        return (
          <Marker
            position={[s.lat, s.lon]}
            icon={s.kind === "landing" ? landingIcon({ highlight: hl }) : takeoffIcon(s, { highlight: hl })}
            zIndexOffset={s.kind === "landing" ? 0 : hl ? 600 : 300}
            title={s.name}
            alt={`${SITE_KIND_LABEL[s.kind]} ${s.name}`}
          >
            <Popup>
              <SitePopupContent site={s} />
            </Popup>
          </Marker>
        );
      }}
    />
  );
}
