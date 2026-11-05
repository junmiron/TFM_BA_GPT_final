const DEFAULT_API_URL = 'http://127.0.0.1:8000';

/**
 * Backend base URL.
 * 1. VITE_API_URL wins (set it when running the Vite dev server separately).
 * 2. Otherwise, if the page is served by the FastAPI app (ui/dist is mounted at
 *    the origin), use that origin - so port 8001/8080 works unchanged.
 * 3. Otherwise fall back to the default local port.
 */
export function resolveApiBaseUrl(): string {
  const configured = (import.meta.env.VITE_API_URL as string | undefined)?.trim();
  if (configured) return configured.replace(/\/+$/, '');

  if (typeof window !== 'undefined' && window.location?.origin) {
    const origin = window.location.origin;
    if (origin && origin !== 'null' && /^https?:\/\//.test(origin)) return origin;
  }
  return DEFAULT_API_URL;
}

export const API_BASE_URL: string = resolveApiBaseUrl();

/** WebSocket base derived from the HTTP base (http -> ws, https -> wss). */
export const WS_BASE_URL: string = API_BASE_URL.replace(/^http/, 'ws');
