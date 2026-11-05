import { useEffect, type Dispatch } from 'react';
import { api } from '../lib/api';
import { errorMessage } from '../lib/format';
import type { Action } from '../state/runState';

const RETRY_MS = 10_000;

/** Checks /api/health on mount and retries every 10 s while the backend is unreachable. */
export function useHealth(dispatch: Dispatch<Action>): void {
  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;

    const check = async () => {
      try {
        const health = await api.health();
        if (!cancelled) dispatch({ type: 'health/loaded', health });
      } catch (error) {
        if (cancelled) return;
        dispatch({ type: 'health/error', message: errorMessage(error) });
        timer = window.setTimeout(check, RETRY_MS);
      }
    };

    void check();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [dispatch]);
}
