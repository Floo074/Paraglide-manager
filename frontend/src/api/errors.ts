/** Erreurs d'API normalisées (backend FastAPI ou moteur de démonstration). */

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

interface PydanticErrorItem {
  loc?: (string | number)[];
  msg?: string;
}

/**
 * Message lisible depuis le `detail` FastAPI :
 *  - `{"detail": "texte"}` (règles métier, query string, 404) ;
 *  - `{"detail": [{loc, msg, type}]}` (validation Pydantic, msg préfixé "Value error, ").
 */
export function describeErrorDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = (detail as PydanticErrorItem[])
      .map((d) => (typeof d?.msg === "string" ? d.msg.replace(/^Value error,\s*/i, "") : null))
      .filter((m): m is string => !!m);
    return msgs.length ? Array.from(new Set(msgs)).join(" ; ") : null;
  }
  return null;
}

/**
 * Message affiché au pilote pour une erreur d'API : traduit les messages techniques connus
 * (422 « indique elevation_m » quand le relief au point n'est pas disponible).
 */
export function pilotErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 422 && /elevation_m/.test(e.message)) {
      return "Relief indisponible pour le moment à cet endroit : indique l'altitude du décollage (champ « Altitude (m) ») puis relance.";
    }
    return e.message;
  }
  return e instanceof Error ? e.message : "Erreur inconnue";
}

/** Texte court d'une erreur de couche (détail du backend si disponible). */
export function layerErrorText(e: Error): string {
  const raw = e instanceof ApiError && typeof e.detail === "string" ? e.detail : e.message;
  return raw.replace(/[\s:]+$/, "");
}

/** Les raisons de rejet du backend commencent par un code : "[LEE_SIDE] Dévent : …". */
export function splitReasonCode(reason: string): { code: string | null; text: string } {
  const m = /^\[([A-Z0-9_]+)\]\s*(.*)$/s.exec(reason.trim());
  return m ? { code: m[1]!, text: m[2]! } : { code: null, text: reason };
}
