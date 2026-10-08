/** Motifs SVG (hachures) référencés en CSS par les polygones Leaflet (zones sensibles). */
export function MapPatterns() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden focusable="false">
      <defs>
        <pattern id="pm-hatch-park" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="8" height="8" fill="rgba(220,38,38,0.10)" />
          <line x1="0" y1="0" x2="0" y2="8" stroke="rgba(220,38,38,0.65)" strokeWidth="2.5" />
        </pattern>
        <pattern id="pm-hatch-active" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="8" height="8" fill="rgba(234,88,12,0.10)" />
          <line x1="0" y1="0" x2="0" y2="8" stroke="rgba(234,88,12,0.7)" strokeWidth="2.5" />
        </pattern>
        <pattern id="pm-hatch-inactive" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
          <line x1="0" y1="0" x2="0" y2="8" stroke="rgba(100,116,139,0.45)" strokeWidth="1.5" />
        </pattern>
      </defs>
    </svg>
  );
}
