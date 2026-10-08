import { FlaskConical, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { checkBackend } from "../../api/client";
import { useApiMode, useBackendDataMode } from "../../hooks/useApiMode";

/** Bandeau visible dès que les données affichées ne sont pas réelles. */
export function DemoBanner() {
  const mode = useApiMode();
  const dataMode = useBackendDataMode();
  const [checking, setChecking] = useState(false);

  // nouvelle tentative automatique toutes les 60 s en cas de repli
  useEffect(() => {
    if (mode !== "demo-fallback") return;
    const id = setInterval(() => void checkBackend(2500), 60_000);
    return () => clearInterval(id);
  }, [mode]);

  if (mode === "live" && (dataMode === "mock" || dataMode === "mixed")) {
    return (
      <div className="demo-banner demo-banner--soft no-print" role="status">
        <FlaskConical size={16} aria-hidden />
        <span>
          {dataMode === "mock" ? "Serveur en mode simulé (DATA_MODE=mock) : données synthétiques" : "Certaines sources du serveur sont simulées"}, ne pas
          utiliser pour voler.
        </span>
      </div>
    );
  }
  if (mode !== "demo-forced" && mode !== "demo-fallback") return null;
  return (
    <div className="demo-banner no-print" role="status">
      <FlaskConical size={16} aria-hidden />
      <span className="grow">
        <strong>Données de démonstration</strong>
        <span className="demo-banner__detail">
          {mode === "demo-forced" ? " — mode démo activé (VITE_USE_MOCKS)." : " — le serveur ne répond pas."} Ne pas utiliser pour voler.
        </span>
      </span>
      {mode === "demo-fallback" ? (
        <button
          type="button"
          className="btn btn--sm btn--ghost-light"
          disabled={checking}
          onClick={async () => {
            setChecking(true);
            await checkBackend(4000);
            setChecking(false);
          }}
        >
          <RefreshCw size={14} aria-hidden className={checking ? "spin" : ""} /> Réessayer
        </button>
      ) : null}
    </div>
  );
}
