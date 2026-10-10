import { alongWindKind, known } from "../../utils/glide";

const KIND_TEXT = { tail: "Vent dans le dos sur le plané", head: "Vent de face sur le plané", weak: "Vent faible sur le plané" } as const;

/**
 * Vent sur le plané relatif au cap : la flèche grise est le cap du pilote vers l'atterro (vers le haut),
 * la flèche colorée le vent le long de la route (vers le haut = dans le dos, vers le bas = de face).
 */
export function GlideWindArrow({ kmh, size = 30 }: { kmh: number | null | undefined; size?: number }) {
  if (!known(kmh)) return null;
  const kind = alongWindKind(kmh);
  const w = 1.8 + Math.min(2.2, Math.abs(kmh) / 10);
  return (
    <svg
      className={`gw-arrow gw-arrow--${kind}`}
      width={size}
      height={size}
      viewBox="0 0 30 30"
      role="img"
      aria-label={KIND_TEXT[kind]}
    >
      <title>{`${KIND_TEXT[kind]}. Flèche grise : ton cap vers l'atterro ; flèche colorée : le vent le long de la route.`}</title>
      <line x1={9} y1={27} x2={9} y2={9} className="gw-arrow__cap" strokeWidth={1.6} strokeDasharray="2.5 2" />
      <path d="M9 3 L12.5 9.5 L5.5 9.5 Z" className="gw-arrow__cap-head" />
      {kind === "weak" ? (
        <circle cx={21} cy={15} r={3.6} className="gw-arrow__wind" fill="none" strokeWidth={1.8} />
      ) : kind === "tail" ? (
        <>
          <line x1={21} y1={27} x2={21} y2={10} className="gw-arrow__wind" strokeWidth={w} strokeLinecap="round" />
          <path d="M21 3 L26 11 L16 11 Z" className="gw-arrow__wind-head" />
        </>
      ) : (
        <>
          <line x1={21} y1={3} x2={21} y2={20} className="gw-arrow__wind" strokeWidth={w} strokeLinecap="round" />
          <path d="M21 27 L26 19 L16 19 Z" className="gw-arrow__wind-head" />
        </>
      )}
    </svg>
  );
}
