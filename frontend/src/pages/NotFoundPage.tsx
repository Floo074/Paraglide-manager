import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="page page--narrow">
      <h1>Page introuvable</h1>
      <p className="muted">Cette adresse ne correspond à aucune page.</p>
      <p>
        <Link to="/" className="btn btn--primary">
          Retour à la planification
        </Link>
      </p>
    </div>
  );
}
