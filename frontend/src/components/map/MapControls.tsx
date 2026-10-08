import { Layers, Minus, Plus, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type L from "leaflet";
import { BASE_LAYERS, type BaseLayerId } from "../../config/map";

export interface OverlayToggle {
  id: string;
  label: ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  hint?: string;
}

/** Bouton "Couches" : choix du fond de carte et des surcouches. */
export function LayersMenu({
  baseLayer,
  onBaseLayer,
  overlays,
  children,
}: {
  baseLayer: BaseLayerId;
  onBaseLayer: (id: BaseLayerId) => void;
  overlays: OverlayToggle[];
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent | TouchEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("touchstart", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("touchstart", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div className="layers-menu" ref={ref}>
      <button type="button" className="map-btn" aria-expanded={open} aria-label="Couches de la carte" title="Couches" onClick={() => setOpen((o) => !o)}>
        {open ? <X size={18} aria-hidden /> : <Layers size={18} aria-hidden />}
      </button>
      {open ? (
        <div className="layers-menu__panel" role="dialog" aria-label="Couches">
          <fieldset>
            <legend>Fond de carte</legend>
            {BASE_LAYERS.map((b) => (
              <label key={b.id} className="check">
                <input type="radio" name="base-layer" checked={baseLayer === b.id} onChange={() => onBaseLayer(b.id)} />
                {b.name}
              </label>
            ))}
          </fieldset>
          {overlays.length ? (
            <fieldset>
              <legend>Surcouches</legend>
              {overlays.map((o) => (
                <label key={o.id} className={`check${o.disabled ? " check--disabled" : ""}`} title={o.hint}>
                  <input type="checkbox" checked={o.checked} disabled={o.disabled} onChange={(e) => o.onChange(e.target.checked)} />
                  <span>
                    {o.label}
                    {o.hint && o.disabled ? <span className="check__hint">{o.hint}</span> : null}
                  </span>
                </label>
              ))}
            </fieldset>
          ) : null}
          {children}
        </div>
      ) : null}
    </div>
  );
}

export function ZoomButtons({ map }: { map: L.Map | null }) {
  return (
    <div className="map-btn-group" role="group" aria-label="Zoom">
      <button type="button" className="map-btn" aria-label="Zoom avant" onClick={() => map?.zoomIn()}>
        <Plus size={18} aria-hidden />
      </button>
      <button type="button" className="map-btn" aria-label="Zoom arrière" onClick={() => map?.zoomOut()}>
        <Minus size={18} aria-hidden />
      </button>
    </div>
  );
}
