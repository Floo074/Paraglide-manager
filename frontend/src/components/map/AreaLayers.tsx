import { Polygon, Popup } from "react-leaflet";
import type { LatLngExpression } from "leaflet";
import type { AirspaceFeature, AirspaceGeometry, SensitiveAreaFeature } from "../../api/types";
import { formatAltitude } from "../../utils/format";
import { mToFt } from "../../utils/units";

/** GeoJSON (lon, lat) → anneaux Leaflet (lat, lon). */
export function geometryToLatLngs(g: AirspaceGeometry): LatLngExpression[][][] {
  const polys = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
  return polys.map((rings) => rings.map((ring) => ring.map((c) => [c[1]!, c[0]!] as [number, number])));
}

const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

/** "févr. → juil." ; toute l'année si 12 mois. */
export function formatMonths(months: number[]): string {
  if (months.length === 0 || months.length >= 12) return "toute l'année";
  const set = new Set(months);
  // trouve le début d'une séquence circulaire
  let start = months[0]!;
  for (const m of months) if (!set.has(((m + 10) % 12) + 1)) start = m;
  const seq: number[] = [];
  for (let i = 0, m = start; i < 12 && set.has(m); i++, m = (m % 12) + 1) seq.push(m);
  if (seq.length === months.length) return `${MONTHS[seq[0]! - 1]} → ${MONTHS[seq[seq.length - 1]! - 1]}`;
  return [...months].sort((a, b) => a - b).map((m) => MONTHS[m - 1]).join(", ");
}

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

const CLASS_COLOR: Record<string, string> = {
  A: "#dc2626",
  B: "#dc2626",
  C: "#9333ea",
  D: "#2563eb",
  E: "#16a34a",
  F: "#0d9488",
  G: "#64748b",
  P: "#b91c1c",
  R: "#ea580c",
};

export function airspaceColor(cls: string, type: string): string {
  const t = type.toUpperCase();
  if (t.includes("PROHIB") || t === "P") return CLASS_COLOR.P!;
  if (t.includes("RESTRICT") || t.includes("DANGER") || t.includes("ZRT")) return CLASS_COLOR.R!;
  return CLASS_COLOR[cls.toUpperCase()] ?? "#475569";
}

export const fl = (m: number) => `FL${String(Math.round(mToFt(m) / 100)).padStart(3, "0")}`;
export const ft = (m: number) => `${Math.round(mToFt(m) / 10) * 10} ft`;

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
