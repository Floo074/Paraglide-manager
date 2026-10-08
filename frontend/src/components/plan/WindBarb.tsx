import { kmhToKt } from "../../utils/units";

/**
 * Barbule de vent météo (convention OMM) : la hampe pointe vers l'origine du vent ;
 * fanion = 50 kt, barbe = 10 kt, demi-barbe = 5 kt.
 */
export function WindBarb({ x, y, speedKmh, dirDeg, size = 26, color = "currentColor" }: { x: number; y: number; speedKmh: number; dirDeg: number; size?: number; color?: string }) {
  let kt = Math.round(kmhToKt(speedKmh) / 5) * 5;
  if (kt < 5) {
    return <circle cx={x} cy={y} r={3} fill="none" stroke={color} strokeWidth={1.4} />;
  }
  const parts: JSX.Element[] = [];
  const step = size / 7;
  let pos = 0; // depuis l'extrémité de la hampe
  let i = 0;
  while (kt >= 50) {
    parts.push(<path key={i++} d={`M0 ${-size + pos} L${size * 0.38} ${-size + pos + step * 0.5} L0 ${-size + pos + step}`} fill={color} />);
    pos += step * 1.2;
    kt -= 50;
  }
  while (kt >= 10) {
    parts.push(<line key={i++} x1={0} y1={-size + pos} x2={size * 0.38} y2={-size + pos - step * 0.7} stroke={color} strokeWidth={1.4} />);
    pos += step;
    kt -= 10;
  }
  if (kt >= 5) {
    if (pos === 0) pos = step;
    parts.push(<line key={i++} x1={0} y1={-size + pos} x2={size * 0.2} y2={-size + pos - step * 0.35} stroke={color} strokeWidth={1.4} />);
  }
  return (
    <g transform={`translate(${x} ${y}) rotate(${dirDeg})`}>
      <line x1={0} y1={0} x2={0} y2={-size} stroke={color} strokeWidth={1.4} />
      {parts}
    </g>
  );
}
