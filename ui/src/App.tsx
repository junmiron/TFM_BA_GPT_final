import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { SessionRail } from './components/SessionRail';
import { Transcript } from './components/Transcript';
import { AnswerBox } from './components/AnswerBox';
import { RunPanel } from './components/RunPanel';
import { ContinueBox } from './components/ContinueBox';
import { Header } from './components/Header';
import { useHealth } from './hooks/useHealth';
import { useSessions } from './hooks/useSessions';
import { useSessionSocket } from './hooks/useSessionSocket';
import { api, downloadArtifact, postFeedback } from './lib/api';
import { errorMessage, formatLanes, sessionTitle } from './lib/format';
import { findSpecArtifact } from './lib/artifacts';
import { shouldFollowLatest } from './lib/scroll';
import { isActiveRun, reducer, initialState, EMPTY_THREAD, awaitingQuestion, stageStates, PENDING_PREFIX, isTerminalRun, type RunStatus, type Thread } from './state/runState';

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const { refresh, scheduleRefresh } = useSessions(dispatch);
  useHealth(dispatch);

  const activeId = state.activeId;
  const thread: Thread = (activeId && state.threads[activeId]) || EMPTY_THREAD;
  const activeSession = state.sessions.find((s) => s.id === activeId) ?? null;

  // Socket hook reads run status through a ref so its effect does not re-run on every event.
  const threadsRef = useRef(state.threads);
  threadsRef.current = state.threads;
  const getRun = useCallback((id: string): RunStatus => threadsRef.current[id]?.run ?? 'idle', []);

  const { send, stop } = useSessionSocket(activeId, dispatch, getRun);

  /** Feature 1: satisfaction gate. REST works for live and persisted sessions alike. */
  const sendFeedback = useCallback(
    (satisfied: boolean, comment: string) => {
      if (!activeId || activeId.startsWith(PENDING_PREFIX)) return;
      void postFeedback(activeId, satisfied, comment);
    },
    [activeId],
  );

  // Debounced refresh: when the active run reaches a terminal state, refresh the session list once.
  const terminal = isTerminalRun(thread.run);
  useEffect(() => {
    if (terminal) scheduleRefresh();
  }, [terminal, scheduleRefresh]);

  // Safety net: if the run finished but the socket never delivered the artifact
  // list (dropped frame during a reconnect), fetch it once so downloads are not lost.
  const refetchedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!activeId || activeId.startsWith(PENDING_PREFIX)) return;
    if (!terminal) return;
    if (thread.artifacts && thread.artifacts.length > 0) return;
    if (refetchedFor.current === activeId) return;
    refetchedFor.current = activeId;
    api
      .listArtifacts(activeId)
      .then((artifacts) => dispatch({ type: 'artifacts/loaded', id: activeId, artifacts }))
      .catch(() => undefined);
  }, [activeId, terminal, thread.artifacts]);

  // Load artifacts for a session when it is selected and has none yet.
  useEffect(() => {
    if (!activeId || activeId.startsWith(PENDING_PREFIX)) return;
    if (thread.artifacts !== null) return;
    let cancelled = false;
    api
      .listArtifacts(activeId)
      .then((artifacts) => {
        if (!cancelled) dispatch({ type: 'artifacts/loaded', id: activeId, artifacts });
      })
      .catch((error: unknown) => {
        if (!cancelled) dispatch({ type: 'artifacts/error', id: activeId, message: errorMessage(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [activeId, thread.artifacts]);

  const retryArtifacts = useCallback(() => {
    if (!activeId) return;
    api
      .listArtifacts(activeId)
      .then((artifacts) => dispatch({ type: 'artifacts/loaded', id: activeId, artifacts }))
      .catch((error: unknown) => dispatch({ type: 'artifacts/error', id: activeId, message: errorMessage(error) }));
  }, [activeId]);

  const startSession = useCallback(
    async (task: string, transcript?: { name: string; base64: string }) => {
      const tempId = `${PENDING_PREFIX}${Date.now()}`;
      dispatch({ type: 'session/createStart', tempId, task });
      try {
        const id = await api.createSession(task, transcript);
        dispatch({ type: 'session/created', tempId, id });
        scheduleRefresh();
      } catch (error) {
        dispatch({ type: 'session/createFailed', tempId, message: errorMessage(error) });
      }
    },
    [scheduleRefresh],
  );

  const selectSession = useCallback((id: string) => dispatch({ type: 'session/select', id }), []);

  const runActive = isActiveRun(thread.run);
  const question = useMemo(() => awaitingQuestion(thread), [thread]);
  const stages = useMemo(() => stageStates(thread), [thread]);
  const specArtifact = thread.artifacts ? findSpecArtifact(thread.artifacts) : undefined;
  const connected = thread.conn === 'open';

  const [downloadError, setDownloadError] = useState<string | null>(null);
  const downloadSpec = useCallback(() => {
    if (!activeId || !specArtifact) return;
    setDownloadError(null);
    downloadArtifact(activeId, specArtifact).catch((error: unknown) => setDownloadError(errorMessage(error)));
  }, [activeId, specArtifact]);

  // Copilot-style: the composer is pinned at the bottom of the chat column,
  // so the transcript scrolls up to keep the latest turn in view. We only
  // auto-scroll when the reader is already near the bottom, so scrolling up
  // to read history is never hijacked by a new agent message.
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = transcriptRef.current;
    if (!el) return;
    if (shouldFollowLatest(el.scrollHeight, el.scrollTop, el.clientHeight, Boolean(question))) {
      el.scrollTop = el.scrollHeight;
    }
  }, [thread.turns, question]);

  // Escape stops an active run (keyboard shortcut from the spec).
  useEffect(() => {
    if (!runActive) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        stop();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [runActive, stop]);

  const lanes = state.health ? formatLanes(state.health.lanes) : [];
  const healthOk = state.health ? true : state.healthError ? false : null;

  return (
    <div className="min-h-screen bg-gradient-to-br from-background to-secondary/30">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:shadow">
        Skip to transcript
      </a>
      <Header
        lanes={lanes}
        healthOk={healthOk}
        healthError={state.healthError}
        specArtifact={specArtifact}
        onDownloadSpec={downloadSpec}
        downloadError={downloadError}
        canStop={runActive}
        onStop={stop}
      />

      <div className="mx-auto grid max-w-[1600px] grid-cols-1 gap-4 p-4 sm:p-6 lg:grid-cols-[18rem_minmax(0,1fr)_18rem] lg:gap-6">
        <SessionRail
          sessions={state.sessions}
          loaded={state.sessionsLoaded}
          error={state.sessionsError}
          activeId={activeId}
          composerError={state.composerError}
          starting={state.sessions.some((s) => s.status === 'starting')}
          onSelect={selectSession}
          onStart={startSession}
          onRetry={() => void refresh()}
        />

        <main
          id="main"
          aria-label="Interview transcript"
          className="flex min-h-[60vh] min-w-0 flex-col gap-4 lg:max-h-[calc(100vh-7rem)]"
        >
          <section aria-label="Live transcript" className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-card shadow-lg">
            <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-3 sm:px-5">
              <h2 className="text-sm font-semibold text-foreground">
                {activeSession ? sessionTitle(activeSession) : 'Transcript'}
              </h2>
              {thread.conn !== 'idle' && activeSession && (
                <span className="text-xs text-muted-foreground" aria-live="polite">
                  {thread.conn === 'open' ? 'Live' : thread.conn === 'reconnecting' ? 'Reconnecting…' : thread.conn === 'connecting' ? 'Connecting…' : 'Disconnected'}
                </span>
              )}
            </div>
            <div ref={transcriptRef} className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
              <Transcript
                turns={thread.turns}
                hasSession={activeId !== null}
                busy={runActive}
                historical={activeId !== null && thread.turns.length === 0 && !runActive}
                showInternal={state.health?.ui?.show_internal !== false}
                onFeedback={sendFeedback}
              />
            </div>
          </section>

          {question && (
            <div className="sticky bottom-0 shrink-0">
              <AnswerBox question={question} connected={connected} onSend={send} />
            </div>
          )}

          {!runActive && activeId && !activeId.startsWith(PENDING_PREFIX) && thread.artifacts && thread.artifacts.length > 0 && (
            <div className="px-4 pb-4">
              <ContinueBox
                sessionId={activeId}
                onInfo={(message) => {
                  dispatch({ type: 'socket/event', id: activeId, event: { type: 'info', content: message } });
                  api.listArtifacts(activeId)
                    .then((artifacts) => dispatch({ type: 'artifacts/loaded', id: activeId, artifacts }))
                    .catch(() => undefined);
                }}
              />
            </div>
          )}
        </main>

        <RunPanel
          sessionId={activeId && !activeId.startsWith(PENDING_PREFIX) ? activeId : null}
          stages={stages}
          runActive={runActive}
          artifacts={thread.artifacts}
          artifactsError={thread.artifactsError}
          onRetryArtifacts={retryArtifacts}
          turns={activeSession?.messages ?? 0}
          turnBudget={state.health?.max_messages ?? null}
          showArtifacts={state.health?.ui?.show_artifacts !== false}
        />
      </div>
    </div>
  );
}
