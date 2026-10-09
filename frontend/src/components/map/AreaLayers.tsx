import { Polygon, Popup } from "react-leaflet";
import type { AirspaceFeature, SensitiveAreaFeature } from "../../api/types";
import { formatAltitude } from "../../utils/format";
import { airspaceColor, fl, formatMonths, ft, geometryToLatLngs } from "./mapHelpers";

const KIND_LABEL: Record<SensitiveAreaFeature["properties"]["kind"], string> = {
  species: "Zone de sensibilité faune",
  regulatory: "Zone réglementée (réserve)",
  national_park_core: "Cœur de parc national",
};

export function SensitiveAreasLayer({ features }: { features: SensitiveAreaFeature[] }) {
  return (
    <>
      {features.map((f, i) => {
        const p = f.properties;
        const active = p.active_now;
        const park = p.kind === "national_park_core";
        // cœurs de parcs : rouge hachuré ; zones faune/réserves actives : orange ; inactives : grisées
        const cls = park ? "sa-poly--park" : active ? "sa-poly--active" : "sa-poly--inactive";
        const color = park ? "#dc2626" : active ? "#ea580c" : "#64748b";
        return (
          <Polygon
            key={p.id ?? i}
            positions={geometryToLatLngs(f.geometry)}
            pathOptions={{
              className: `sa-poly ${cls}`,
              color,
              weight: active || park ? 2 : 1.5,
              dashArray: active || park ? undefined : "5 5",
              fillOpacity: 1,
            }}
          >
            <Popup>
              <div className="popup">
                <div className="popup__title">{p.name}</div>
                <div className="popup__meta">
                  {KIND_LABEL[p.kind]}
                  {p.species ? ` · ${p.species}` : ""}
                </div>
                <div>
                  <span className="muted">Sensibilité :</span> {formatMonths(p.period_months)}{" "}
                  <strong className={active ? "text-nogo" : "muted"}>{active ? "(active)" : "(inactive à cette date)"}</strong>
                </div>
                {p.min_height_agl_m !== null ? (
                  <div>
                    <span className="muted">Survol :</span> au moins {formatAltitude(p.min_height_agl_m)} sol
                  </div>
                ) : null}
                <p className="popup__warn">{p.recommendation}</p>
                <div className="popup__foot">
                  Source : {p.source === "biodivsports" ? "Biodiv'Sports" : "données de démonstration"}
                  {p.url ? (
                    <>
                      {" · "}
                      <a href={p.url} target="_blank" rel="noreferrer">
                        en savoir plus
                      </a>
                    </>
                  ) : null}
                </div>
              </div>
            </Popup>
          </Polygon>
        );
      })}
    </>
  );
}

export function AirspacesLayer({ features }: { features: AirspaceFeature[] }) {
  return (
    <>
      {features.map((f, i) => {
        const p = f.properties;
        const color = airspaceColor(p.airspace_class, p.type);
        return (
          <Polygon
            key={`${p.name}-${i}`}
            positions={geometryToLatLngs(f.geometry)}
            pathOptions={{ color, weight: 2, fillColor: color, fillOpacity: 0.08, dashArray: p.floor_m > 0 ? "8 4" : undefined, className: "as-poly" }}
          >
            <Popup>
              <div className="popup">
                <div className="popup__title">{p.name}</div>
                <div className="popup__meta">
                  Classe {p.airspace_class} · {p.type}
                </div>
                <table className="popup__table">
                  <tbody>
                    <tr>
                      <th>Plafond</th>
                      <td>
                        {formatAltitude(p.ceiling_m)} <span className="muted">({ft(p.ceiling_m)} · {fl(p.ceiling_m)})</span>
                      </td>
                    </tr>
                    <tr>
                      <th>Plancher</th>
                      <td>
                        {p.floor_m <= 0 ? "Sol (SFC)" : formatAltitude(p.floor_m)}{" "}
                        {p.floor_m > 0 ? <span className="muted">({ft(p.floor_m)})</span> : null}
                        {p.floor_reference === "GND" && p.floor_m > 0 ? <span className="muted"> — publié par rapport au sol</span> : null}
                      </td>
                    </tr>
                  </tbody>
                </table>
                <p className="popup__foot">Altitudes AMSL. Vérifier les activations (NOTAM, SUP AIP) avant le vol.</p>
              </div>
            </Popup>
          </Polygon>
        );
      })}
    </>
  );
}
