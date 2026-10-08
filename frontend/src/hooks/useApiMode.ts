import { useSyncExternalStore } from "react";
import { getApiMode, getBackendDataMode, subscribeApiMode, type ApiMode } from "../api/client";

export function useApiMode(): ApiMode {
  return useSyncExternalStore(subscribeApiMode, getApiMode, getApiMode);
}

/** Mode de données annoncé par le backend (/api/health) : live, mock ou mixed. */
export function useBackendDataMode() {
  return useSyncExternalStore(subscribeApiMode, getBackendDataMode, getBackendDataMode);
}
