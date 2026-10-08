export const TOAST_EVENT = "pm:toast";

/** Affiche un message éphémère (aria-live). */
export function toast(message: string): void {
  window.dispatchEvent(new CustomEvent<string>(TOAST_EVENT, { detail: message }));
}
