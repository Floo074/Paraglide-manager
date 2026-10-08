import { useEffect } from "react";
import { usePersistentState } from "./usePersistentState";

export type ThemePref = "system" | "dark" | "light";
const isPref = (v: unknown): v is ThemePref => v === "system" || v === "dark" || v === "light";

/** Thème : suit le système par défaut, forçable en sombre/clair (attribut data-theme sur <html>). */
export function useTheme() {
  const [pref, setPref] = usePersistentState<ThemePref>("pm.theme", "system", isPref);
  useEffect(() => {
    const root = document.documentElement;
    if (pref === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", pref);
  }, [pref]);
  const cycle = () => setPref((p) => (p === "system" ? "dark" : p === "dark" ? "light" : "system"));
  return { pref, setPref, cycle };
}
