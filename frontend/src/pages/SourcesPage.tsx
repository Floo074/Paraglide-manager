import { CheckCircle2, CircleSlash, KeyRound, RefreshCw, XCircle } from "lucide-react";
import { FORCE_MOCKS, checkBackend, getBackendDataMode, getHealth, getSources } from "../api/client";
import type { SourceKind, SourceStatus } from "../api/types";
import { Card } from "../components/ui/Card";
import { ErrorBox, Spinner } from "../components/ui/Spinner";
import { BASE_LAYERS, KK7 } from "../config/map";
import { useApiMode } from "../hooks/useApiMode";
import { useAsync } from "../hooks/useAsync";

const KIND_LABEL: Record<SourceKind, string> = {
  forecast: "Prévisions météo",
  sites: "Sites de vol",
  beacons: "Balises vent",
  airspaces: "Espaces aériens",
  sensitive_areas: "Zones sensibles",
  elevation: "Altitude du terrain",
};
const KIND_ORDER: SourceKind[] = ["forecast", "beacons", "sites", "airspaces", "sensitive_areas", "elevation"];

/** Aide "Comment l'activer" selon la source (complète le `message` du backend). */
function activationHelp(s: SourceStatus): React.ReactNode | null {
  const name = s.name.toLowerCase();
  const needsHelp = s.mode === "disabled" || (s.requires_api_key && !s.api_key_configured) || !s.healthy;
  if (!needsHelp) return null;
  if (name.includes("ffvl")) {
    return (
      <>
        Renseigner la variable <code>FFVL_API_KEY</code> dans l'environnement du backend (<code>backend/.env</code>), puis redémarrer le backend. La clé
        s'obtient auprès de la FFVL (data.ffvl.fr).
      </>
    );
  }
  if (name.includes("openaip") || s.kind === "airspaces") {
    return (
      <>
        Renseigner <code>OPENAIP_API_KEY</code> (clé gratuite sur openaip.net) dans <code>backend/.env</code>, puis redémarrer. <strong>Sans clé :</strong> déposer
        un ou plusieurs fichiers au format OpenAir dans <code>backend/data/airspaces/</code> ; le backend les lit au démarrage.
      </>
    );
  }
  if (name.includes("spotair") || name.includes("météo-parapente") || name.includes("meteo-parapente")) {
    return <>Pas d'API publique : l'adaptateur est prêt côté backend mais nécessite un accord ou une licence avec l'éditeur.</>;
  }
  if (s.requires_api_key && !s.api_key_configured) {
    return <>Clé d'API à renseigner dans l'environnement du backend (<code>backend/.env</code>), puis redémarrer.</>;
  }
  if (!s.healthy && s.mode !== "disabled") {
    return <>Source injoignable : vérifier l'accès réseau du backend. En mode <code>DATA_MODE=auto</code>, le backend se replie sur les données simulées.</>;
  }
  return null;
}

function ModeBadge({ s }: { s: SourceStatus }) {
  if (s.mode === "live") return <span className="badge badge--go">Réel</span>;
  if (s.mode === "mock") return <span className="badge badge--marginal">Simulé</span>;
  return <span className="badge badge--neutral">Désactivé</span>;
}

export function SourcesPage() {
  const mode = useApiMode();
  const sources = useAsync((s) => getSources(s), [mode]);
  const health = useAsync(() => getHealth(), [mode]);
  const grouped = KIND_ORDER.map((k) => ({ kind: k, items: (sources.data?.sources ?? []).filter((s) => s.kind === k) })).filter((g) => g.items.length);
  const others = (sources.data?.sources ?? []).filter((s) => !KIND_ORDER.includes(s.kind));

  return (
    <div className="page">
      <div className="page__head">
        <h1>Sources & statut</h1>
        <button type="button" className="btn btn--sm" onClick={() => void checkBackend(4000).then(() => sources.reload())}>
          <RefreshCw size={14} aria-hidden /> Actualiser
        </button>
      </div>
      <Card title="Connexion">
        <dl className="kv">
          <dt>Serveur (backend)</dt>
          <dd>
            {mode === "live" ? (
              <span className="text-go">
                <CheckCircle2 size={15} aria-hidden /> joignable
              </span>
            ) : mode === "demo-forced" ? (
              <span className="text-marginal">non utilisé (VITE_USE_MOCKS=true)</span>
            ) : mode === "demo-fallback" ? (
              <span className="text-nogo">
                <XCircle size={15} aria-hidden /> injoignable — données de démonstration
              </span>
            ) : (
              "vérification…"
            )}
          </dd>
          <dt>Mode des données</dt>
          <dd>
            {mode === "live" ? (getBackendDataMode() ?? health.data?.data_mode ?? "—") : "démonstration (navigateur)"}
            {health.data?.version ? <span className="faint small"> · version {health.data.version}</span> : null}
          </dd>
          <dt>Fonds de carte</dt>
          <dd>{BASE_LAYERS.map((b) => b.name).join(", ")} — sans clé d'API</dd>
          <dt>Hotspots KK7</dt>
          <dd>{KK7.url ? "configurés (VITE_KK7_TILES_URL)" : "non configurés (renseigner VITE_KK7_TILES_URL au build du frontend)"}</dd>
          {FORCE_MOCKS ? (
            <>
              <dt>Frontend</dt>
              <dd>build en mode démonstration</dd>
            </>
          ) : null}
        </dl>
      </Card>

      {sources.loading && !sources.data ? <Spinner /> : null}
      {sources.error ? <ErrorBox error={sources.error} onRetry={sources.reload} /> : null}

      {[...grouped, ...(others.length ? [{ kind: "autres" as const, items: others }] : [])].map((g) => (
        <Card key={g.kind} title={g.kind === "autres" ? "Autres" : KIND_LABEL[g.kind]}>
          <ul className="source-list">
            {g.items.map((s) => {
              const help = activationHelp(s);
              return (
                <li key={s.name} className={`source source--${s.mode}`}>
                  <div className="source__head">
                    <span className="source__name">
                      {s.url ? (
                        <a href={s.url} target="_blank" rel="noreferrer">
                          {s.name}
                        </a>
                      ) : (
                        s.name
                      )}
                    </span>
                    <ModeBadge s={s} />
                    {s.mode !== "disabled" ? (
                      s.healthy ? (
                        <span className="text-go small">
                          <CheckCircle2 size={14} aria-hidden /> OK
                        </span>
                      ) : (
                        <span className="text-nogo small">
                          <XCircle size={14} aria-hidden /> en erreur
                        </span>
                      )
                    ) : (
                      <CircleSlash size={14} aria-hidden className="faint" />
                    )}
                  </div>
                  {s.requires_api_key ? (
                    <div className="small muted">
                      <KeyRound size={13} aria-hidden /> Clé d'API requise : {s.api_key_configured ? <span className="text-go">configurée</span> : <span className="text-marginal">non configurée</span>}
                    </div>
                  ) : null}
                  {s.message ? <p className="small">{s.message}</p> : null}
                  {help ? (
                    <div className="howto">
                      <strong>Comment l'activer :</strong> {help}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </Card>
      ))}
    </div>
  );
}
