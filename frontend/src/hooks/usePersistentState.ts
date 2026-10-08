import { useEffect, useState } from "react";
import { loadJson, saveJson } from "../utils/storage";

/** useState mémorisé dans localStorage (clé versionnée). */
export function usePersistentState<T>(key: string, initial: T | (() => T), validate?: (v: unknown) => v is T) {
  const [value, setValue] = useState<T>(() => {
    const fallback = typeof initial === "function" ? (initial as () => T)() : initial;
    const stored = loadJson<unknown>(key, undefined);
    if (stored === undefined) return fallback;
    if (validate && !validate(stored)) return fallback;
    return stored as T;
  });
  useEffect(() => {
    saveJson(key, value);
  }, [key, value]);
  return [value, setValue] as const;
}
