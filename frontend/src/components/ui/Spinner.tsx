export function Spinner({ label = "Chargement…" }: { label?: string }) {
  return (
    <span className="spinner-wrap" role="status">
      <span className="spinner" aria-hidden />
      <span className="spinner-label">{label}</span>
    </span>
  );
}

export function ErrorBox({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="alert alert--danger" role="alert">
      <span className="grow">{error.message}</span>
      {onRetry ? (
        <button type="button" className="btn btn--sm" onClick={onRetry}>
          Réessayer
        </button>
      ) : null}
    </div>
  );
}
