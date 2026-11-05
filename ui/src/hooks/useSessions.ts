import { useCallback, useEffect, useRef, type Dispatch } from 'react';
import { api } from '../lib/api';
import { errorMessage } from '../lib/format';
import type { Action } from '../state/runState';

/** Session list loader with a debounced refresh for bursts of run events. */
export function useSessions(dispatch: Dispatch<Action>) {
  const timer = useRef<number | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      const sessions = await api.listSessions();
      dispatch({ type: 'sessions/loaded', sessions });
    } catch (error) {
      dispatch({ type: 'sessions/error', message: errorMessage(error) });
    }
  }, [dispatch]);

  const scheduleRefresh = useCallback(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void refresh(), 400);
  }, [refresh]);

  useEffect(() => {
    void refresh();
    return () => window.clearTimeout(timer.current);
  }, [refresh]);

  return { refresh, scheduleRefresh };
}
