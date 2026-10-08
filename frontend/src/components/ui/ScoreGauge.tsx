import { scoreColor } from "../../utils/colors";

/** Jauge circulaire du score (0..100). */
export function ScoreGauge({ score, size = 52, label = "Score" }: { score: number; size?: number; label?: string }) {
  const s = Math.max(0, Math.min(100, score));
  const stroke = Math.max(4, size / 10);
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div className="score-gauge" style={{ width: size, height: size }} role="img" aria-label={`${label} : ${Math.round(s)} sur 100`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--bg-sunken)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={scoreColor(s)}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${(c * s) / 100} ${c}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <span className="score-gauge__value" style={{ fontSize: size * 0.32 }}>
        {Math.round(s)}
      </span>
    </div>
  );
}

/** Barre horizontale de score (décomposition). */
export function ScoreBar({ score }: { score: number }) {
  const s = Math.max(0, Math.min(100, score));
  return (
    <div className="score-bar" aria-hidden>
      <div className="score-bar__fill" style={{ width: `${s}%`, background: scoreColor(s) }} />
    </div>
  );
}
