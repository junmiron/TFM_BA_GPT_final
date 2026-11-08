import { useCallback, useEffect, useRef, useState, useReducer } from 'react';
import { Transcript } from '../../ui/src/components/Transcript';
import { RunPanel } from '../../ui/src/components/RunPanel';
import { EMPTY_THREAD, initialState, isTerminalRun, reducer, stageStates } from '../../ui/src/state/runState';
import { shouldFollowLatest } from '../../ui/src/lib/scroll';
import { formatLanes } from '../../ui/src/lib/format';
import type { ServerEvent } from '../../ui/src/lib/types';
import { DemoHeader } from './components/DemoHeader';
import { StartHero } from './components/StartHero';
import { PlaybackBar } from './components/PlaybackBar';
import { ArtifactViewer } from './components/ArtifactViewer';
import { clampSpeed, firstNotDue, loadReplay, totalSpan, type ReplayData } from './replay';

/**
 * Demo scheduler. The recorded log has real UTC timestamps; the demo keeps a
 * "virtual clock" that advances TICK_MS * speed ms per real tick and dispatches
 * every event whose recorded offset is <= that clock, in order, into the same
 * reducer the product uses. Pause simply stops the clock advancing.
 */
const TICK_MS = 100;
const SESSION_ID = 'demo';

export default function App() {
  const [data, setData] = useState<ReplayData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [started, setStarted] = useState(false);
  const [paused, setPaused] = useState(false);
  const params = new URLSearchParams(window.location.search);
  const [speed, setSpeed] = useState(clampSpeed(params.get('speed')));
  const [showInternal, setShowInternal] = useState(params.get('agents') !== '0');

  const [state, dispatch] = useReducer(reducer, initialState);

  // Mutable scheduler state; reading it in render is unnecessary.
  const clockRef = useRef(0);
  const cursorRef = useRef(0);
  const lastWallRef = useRef(0);
  const [clockDisplay, setClockDisplay] = useState(0);
  const transcriptRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    loadReplay()
      .then(setData)
      .catch((error: unknown) => {
        setLoadError(error instanceof Error ? error.message : 'Could not load the demo data.');
      });
  }, []);

  const start = useCallback(() => {
    if (!data) return;
    clockRef.current = 0;
    cursorRef.current = 0;
    lastWallRef.current = Date.now();
    dispatch({ type: 'session/createStart', tempId: SESSION_ID, task: data.meta.task });
    setStarted(true);
    setPaused(false);
    setClockDisplay(0);
  }, [data, dispatch]);

  useEffect(() => {
    if (!started || paused || !data) return undefined;
    lastWallRef.current = Date.now();
    const timer = window.setInterval(() => {
      // Wall-clock based virtual time: even if the browser throttles the
      // interval (background tabs, headless), the replay stays accurate.
      const now = Date.now();
      clockRef.current += (now - lastWallRef.current) * speed;
      lastWallRef.current = now;
      const next = firstNotDue(data.offsets, cursorRef.current, clockRef.current);
      for (let i = cursorRef.current; i < next; i += 1) {
        dispatch({
          type: 'socket/event',
          id: SESSION_ID,
          event: data.events[i] as unknown as ServerEvent,
        });
      }
      cursorRef.current = next;
      setClockDisplay(clockRef.current);
    }, TICK_MS);
    return () => window.clearInterval(timer);
  }, [started, paused, speed, data, dispatch]);

  const jumpToEnd = () => {
    if (!data) return;
    const next = data.offsets.length;
    for (let i = cursorRef.current; i < next; i += 1) {
      dispatch({ type: 'socket/event', id: SESSION_ID, event: data.events[i] as unknown as ServerEvent });
    }
    cursorRef.current = next;
    clockRef.current = totalSpan(data.offsets);
    setClockDisplay(clockRef.current);
  };

  const thread = state.threads[SESSION_ID] ?? EMPTY_THREAD;
  const finished = isTerminalRun(thread.run);
  const busy = started && !finished;
  const totalMs = data ? totalSpan(data.offsets) : 0;
  const lanes = data?.meta.lanes ? formatLanes(data.meta.lanes) : [];

  // Same auto-scroll rule as the product: follow the latest turn unless the
  // reader has scrolled up to read history.
  useEffect(() => {
    const el = transcriptRef.current;
    if (!el) return;
    if (shouldFollowLatest(el.scrollHeight, el.scrollTop, el.clientHeight, false)) {
      el.scrollTop = el.scrollHeight;
    }
  }, [thread.turns]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-background to-secondary/30">
      <DemoHeader lanes={lanes} />
      {!started ? (
        <StartHero meta={data?.meta ?? { task: '' }} onStart={start} loading={!data && !loadError} error={loadError} />
      ) : (
        <div className="mx-auto grid max-w-[1600px] grid-cols-1 gap-4 p-4 sm:p-6 lg:grid-cols-[minmax(0,1fr)_18rem] lg:gap-6">
          <main id="main" aria-label="Interview transcript" className="flex min-h-[60vh] min-w-0 flex-col gap-4">
            <section aria-label="Live transcript" className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-card shadow-lg">
              <div ref={transcriptRef} className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
                <Transcript turns={thread.turns} hasSession busy={busy} historical={false} showInternal={showInternal} />
              </div>
            </section>

            {finished && thread.artifacts && thread.artifacts.length > 0 && <ArtifactViewer artifacts={thread.artifacts} />}

            <div className="sticky bottom-0">
              <PlaybackBar
                paused={paused}
                speed={speed}
                showInternal={showInternal}
                elapsedMs={clockDisplay}
                totalMs={totalMs}
                finished={finished}
                onTogglePause={() => setPaused((p) => !p)}
                onSpeed={setSpeed}
                onShowInternal={setShowInternal}
                onRestart={start}
                onJumpToEnd={jumpToEnd}
              />
            </div>
          </main>

          <RunPanel
            sessionId={SESSION_ID}
            stages={stageStates(thread)}
            runActive={busy}
            artifacts={thread.artifacts}
            artifactsError={thread.artifactsError}
            onRetryArtifacts={() => undefined}
            turns={thread.turns.length}
            turnBudget={null}
            showArtifacts
          />
        </div>
      )}
    </div>
  );
}
