import { ShieldAlert } from "lucide-react";

export function Disclaimer({ compact = false }: { compact?: boolean }) {
  return (
    <p className={`disclaimer${compact ? " disclaimer--compact" : ""}`} role="note">
      <ShieldAlert size={compact ? 14 : 16} aria-hidden />
      <span>
        Outil d'aide à la décision : il ne remplace pas l'analyse du pilote sur place (observation du ciel, des balises,
        des autres ailes) ni les consignes du site.
      </span>
    </p>
  );
}
