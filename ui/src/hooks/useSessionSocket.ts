import { useCallback, useEffect, useRef, type Dispatch } from 'react';
import { api, sessionSocketUrl, parseServerEvent, answerEvent, stopEvent } from '../lib/api';
import type { Action, RunStatus } from '../state/runState';
import { isPendingId, isTerminalRun } from '../state/runState';

const MAX_RETRIES = 6;
const MAX_BACKOFF_MS = 15_000;

export interface SocketControls {
  /** Sends a human answer. Returns false (and sends nothing) when the socket is not open. */
  send: (content: string) => boolean;
  /** Cancels the run server-side (WebSocket `stop` plus the REST fallback),
  then closes the local socket and marks the run stopped in this window. */
  stop: () => void;
}

/**
 * Owns the WebSocket for the active session. Reconnects with exponential
 * backoff unless the run is already terminal, retries are exhausted, or the
 * user stopped it. `getRun` must be a stable callback that reads the latest state.
 */
export function useSessionSocket(
  sessionId: string | null,
  dispatch: Dispatch<Action>,
  getRun: (id: string) => RunStatus,
): SocketControls {
  const socketRef = useRef<WebSocket | null>(null);
  const retryTimer = useRef<number | undefined>(undefined);
  const sessionRef = useRef<string | null>(sessionId);
  sessionRef.current = sessionId;

  useEffect(() => {
    if (!sessionId || isPendingId(sessionId)) return undefined;

    let cancelled = false;
    let attempt = 0;

    const connect = () => {
      if (cancelled) return;
      dispatch({ type: 'socket/conn', id: sessionId, conn: attempt === 0 ? 'connecting' : 'reconnecting' });

      let ws: WebSocket;
      try {
        ws = new WebSocket(sessionSocketUrl(sessionId));
      } catch {
        dispatch({ type: 'socket/conn', id: sessionId, conn: 'closed' });
        return;
      }
      socketRef.current = ws;

      ws.onopen = () => {
        attempt = 0;
        dispatch({ type: 'socket/conn', id: sessionId, conn: 'open' });
      };

      ws.onmessage = (message: MessageEvent) => {
        const event = parseServerEvent(message.data);
        if (event) dispatch({ type: 'socket/event', id: sessionId, event });
      };

      // onerror is always followed by onclose, which owns the reconnect logic.
      ws.onclose = () => {
        if (socketRef.current === ws) socketRef.current = null;
        if (cancelled) return;
        if (isTerminalRun(getRun(sessionId)) || attempt >= MAX_RETRIES) {
          dispatch({ type: 'socket/conn', id: sessionId, conn: 'closed' });
          return;
        }
        const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt);
        attempt += 1;
        dispatch({ type: 'socket/conn', id: sessionId, conn: 'reconnecting' });
        retryTimer.current = window.setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      cancelled = true;
      window.clearTimeout(retryTimer.current);
      const ws = socketRef.current;
      socketRef.current = null;
      if (ws) {
        ws.onclose = null;
        ws.close(1000, 'session changed');
      }
    };
  }, [sessionId, dispatch, getRun]);

  const send = useCallback(
    (content: string): boolean => {
      const id = sessionRef.current;
      const ws = socketRef.current;
      if (!id || !ws || ws.readyState !== WebSocket.OPEN) return false;
      ws.send(JSON.stringify(answerEvent(content)));
      dispatch({ type: 'answer/sent', id, content });
      return true;
    },
    [dispatch],
  );

  const stop = useCallback(() => {
    const id = sessionRef.current;
    window.clearTimeout(retryTimer.current);
    const ws = socketRef.current;
    socketRef.current = null;
    if (ws && ws.readyState === WebSocket.OPEN) {
      // Ask the server to cancel the AutoGen run, then close the socket.
      ws.send(JSON.stringify(stopEvent()));
    }
    if (ws) {
      ws.onclose = null;
      ws.close(1000, 'stopped by user');
    }
    // Belt and braces: the REST stop is authoritative and works even if the
    // socket was already gone.
    if (id && !isPendingId(id)) void api.stopSession(id).catch(() => undefined);
    if (id) dispatch({ type: 'run/stopped', id });
  }, [dispatch]);

  return { send, stop };
}
