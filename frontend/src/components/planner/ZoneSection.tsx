import { MapPin } from "lucide-react";
import type { Zone } from "../../api/types";
import { PRESET_ZONES } from "../../config/zones";
import { MAX_RADIUS_KM, MIN_RADIUS_KM, describeZone, serializeZone, validateZone } from "../../utils/zone";

export function ZoneSection({ zone, onZone }: { zone: Zone; onZone: (z: Zone) => void }) {
  const current = serializeZone(zone);
  const error = validateZone(zone);
  return (
    <section className="field" aria-labelledby="f-zone">
      <h3 className="field__label" id="f-zone">
        <MapPin size={16} aria-hidden /> Où ? <span className="field__aside">{describeZone(zone)}</span>
      </h3>
      <div className="chips chips--scroll" role="group" aria-label="Zones prédéfinies">
        {PRESET_ZONES.map((p) => {
          const on = serializeZone(p.zone) === current;
          return (
            <button key={p.id} type="button" className={`chip${on ? " chip--on" : ""}`} aria-pressed={on} title={p.region} onClick={() => onZone(p.zone)}>
              <span className="chip__label">{p.name}</span>
            </button>
          );
        })}
      </div>
      {zone.type === "circle" ? (
        <div className="row radius-row">
          <label htmlFor="radius" className="small muted nowrap">
            Rayon
          </label>
          <input
            id="radius"
            type="range"
            className="range"
            min={MIN_RADIUS_KM}
            max={80}
            step={1}
            value={Math.min(80, zone.radius_km)}
            onChange={(e) => onZone({ ...zone, radius_km: Number(e.target.value) })}
          />
          <span className="num small nowrap">{Math.round(zone.radius_km)} km</span>
        </div>
      ) : null}
      <p className="hint">Dessine un rectangle ou un cercle avec les outils de la carte (max {MAX_RADIUS_KM} km de rayon / 3° de côté).</p>
      {error ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
