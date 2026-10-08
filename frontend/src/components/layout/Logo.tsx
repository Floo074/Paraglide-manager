/** Logo : voile de parapente stylisée. */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden className="logo">
      <path d="M3 12 C 9 4, 23 4, 29 12 L 26 13.5 C 21 8.5, 11 8.5, 6 13.5 Z" fill="var(--accent)" />
      <path d="M6 13.5 L15 24 M11 10.5 L15.5 24 M21 10.5 L16.5 24 M26 13.5 L17 24" stroke="var(--text-muted)" strokeWidth="1" fill="none" />
      <circle cx="16" cy="25.5" r="2.3" fill="var(--text)" />
    </svg>
  );
}
