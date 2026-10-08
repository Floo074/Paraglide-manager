import { useSyncExternalStore } from "react";
import { getApiMode, subscribeApiMode, type ApiMode } from "../api/client";

export function useApiMode(): ApiMode {
  return useSyncExternalStore(subscribeApiMode, getApiMode, getApiMode);
}
