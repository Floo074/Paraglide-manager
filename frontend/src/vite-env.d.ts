/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_MOCKS?: string;
  readonly VITE_API_PROXY_TARGET?: string;
  readonly VITE_KK7_TILES_URL?: string;
  readonly VITE_KK7_TMS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
