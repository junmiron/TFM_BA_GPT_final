import type { Artifact, HealthResponse, ServerEvent, SessionSummary } from '../lib/types';
import { extractQuestion, sessionTitle } from '../lib/format';
import { deriveStageStates, type StageId, type StageState } from '../lib/workflow';

export const PENDING_PREFIX = 'pending-';

export type ConnState = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed';
export type RunStatus = 'idle' | 'starting' | 'running' | 'finished' | 'failed' | 'stopped';

export interface Turn {
  id: number;
  kind: 'agent' | 'user' | 'info' | 'error' | 'feedback';
  source: string;
  content: string;
  /** True while chunk events are still arriving for this turn. */
  streaming: boolean;
  /** True for a user answer the server has not echoed back yet. */
  pending: boolean;
  at: number;
}

export interface Thread {
  turns: Turn[];
  run: RunStatus;
  conn: ConnState;
  artifacts: Artifact[] | null;
  artifactsError: string | null;
}

export interface RunState {
  sessions: SessionSummary[];
  sessionsLoaded: boolean;
  sessionsError: string | null;
  activeId: string | null;
  threads: Record<string, Thread>;
  health: HealthResponse | null;
  healthError: string | null;
  composerError: string | null;
}

export type Action =
  | { type: 'sessions/loaded'; sessions: SessionSummary[] }
  | { type: 'sessions/error'; message: string }
  | { type: 'session/select'; id: string }
  | { type: 'session/createStart'; tempId: string; task: string }
  | { type: 'session/created'; tempId: string; id: string }
  | { type: 'session/createFailed'; tempId: string; message: string }
  | { type: 'socket/conn'; id: string; conn: ConnState }
  | { type: 'socket/event'; id: string; event: ServerEvent }
  | { type: 'answer/sent'; id: string; content: string }
  | { type: 'run/stopped'; id: string }
  | { type: 'artifacts/loaded'; id: string; artifacts: Artifact[] }
  | { type: 'artifacts/error'; id: string; message: string }
  | { type: 'health/loaded'; health: HealthResponse }
  | { type: 'health/error'; message: string };

export const EMPTY_THREAD: Thread = {
  turns: [],
  run: 'idle',
  conn: 'idle',
  artifacts: null,
  artifactsError: null,
};

export const initialState: RunState = {
  sessions: [],
  sessionsLoaded: false,
  sessionsError: null,
  activeId: null,
  threads: {},
  health: null,
  healthError: null,
  composerError: null,
};

export function isPendingId(id: string): boolean {
  return id.startsWith(PENDING_PREFIX);
}

export function isActiveRun(run: RunStatus): boolean {
  return run === 'starting' || run === 'running';
}

export function isTerminalRun(run: RunStatus): boolean {
  return run === 'finished' || run === 'failed' || run === 'stopped';
}

/** Maps a server session status onto a run status for sessions opened from history. */
function runFromStatus(status: string): RunStatus {
  if (status === 'completed' || status === 'done') return 'finished';
  if (status === 'failed') return 'failed';
  if (status === 'stopped') return 'stopped';
  if (status === 'running') return 'running';
  return 'idle';
}

type TurnInput = Omit<Turn, 'id' | 'at'>;

function threadOf(state: RunState, id: string): Thread {
  return state.threads[id] ?? EMPTY_THREAD;
}

function withThread(state: RunState, id: string, thread: Thread): RunState {
  return { ...state, threads: { ...state.threads, [id]: thread } };
}

function pushTurn(turns: Turn[], input: TurnInput): Turn[] {
  return [...turns, { ...input, id: turns.length, at: Date.now() }];
}

/** Closes any still-streaming turns and confirms optimistic user answers. */
function settle(turns: Turn[]): Turn[] {
  if (!turns.some((t) => t.streaming || t.pending)) return turns;
  return turns.map((t) => (t.streaming || t.pending ? { ...t, streaming: false, pending: false } : t));
}

function setSessionStatus(
  sessions: SessionSummary[],
  id: string,
  status: string,
  artifactCount?: number,
): SessionSummary[] {
  return sessions.map((s) =>
    s.id === id ? { ...s, status, artifact_count: artifactCount ?? s.artifact_count } : s,
  );
}

function applyEvent(state: RunState, id: string, event: ServerEvent): RunState {
  const thread = threadOf(state, id);
  const starting = thread.run === 'starting';
  const running: RunStatus = starting ? 'running' : thread.run;

  switch (event.type) {
    case 'feedback_request':
      return withThread(state, id, {
        ...thread,
        turns: pushTurn(settle(thread.turns), {
          kind: 'feedback',
          source: 'system',
          content: event.question,
          streaming: false,
          pending: false,
        }),
      });

    case 'info':
      return withThread(state, id, {
        ...thread,
        run: running,
        turns: pushTurn(settle(thread.turns), {
          kind: 'info',
          source: 'system',
          content: event.content,
          streaming: false,
          pending: false,
        }),
      });

    case 'answer': {
      // Server echo of a human answer. Confirm the optimistic turn if one matches.
      const turns = [...thread.turns];
      for (let i = turns.length - 1; i >= 0; i -= 1) {
        const turn = turns[i];
        // Match the optimistic answer even if a later event already settled it,
        // otherwise the echo would render the same answer twice.
        if (turn.kind === 'user' && turn.content === event.content) {
          turns[i] = { ...turn, pending: false };
          return withThread(state, id, { ...thread, turns });
        }
      }
      return withThread(state, id, {
        ...thread,
        turns: pushTurn(turns, {
          kind: 'user',
          source: 'user',
          content: event.content,
          streaming: false,
          pending: false,
        }),
      });
    }

    case 'chunk': {
      let turns = thread.turns;
      const last = turns[turns.length - 1];
      if (last && last.kind === 'agent' && last.streaming && last.source === event.source) {
        turns = turns.slice(0, -1).concat({ ...last, content: last.content + event.content });
      } else {
        turns = pushTurn(settle(turns), {
          kind: 'agent',
          source: event.source,
          content: event.content,
          streaming: true,
          pending: false,
        });
      }
      return withThread(state, id, { ...thread, run: running, turns });
    }

    case 'message': {
      // The pipeline echoes the human's reply as a normal message. Show it once:
      // if it matches an optimistic answer, settle that turn instead of adding a
      // second copy.
      if (event.source.toLowerCase() === 'user') {
        return applyEvent(state, id, { type: 'answer', content: event.content });
      }
      // A full message closes the matching streamed turn, or starts a new one.
      let turns = thread.turns;
      const last = turns[turns.length - 1];
      if (last && last.kind === 'agent' && last.streaming && last.source === event.source) {
        turns = turns.slice(0, -1).concat({ ...last, content: event.content, streaming: false });
      } else {
        turns = pushTurn(settle(turns), {
          kind: 'agent',
          source: event.source,
          content: event.content,
          streaming: false,
          pending: false,
        });
      }
      return withThread(state, id, { ...thread, run: running, turns });
    }

    case 'complete': {
      // Never wipe a list the UI already fetched: the authoritative
      // artifact list arrives with the `artifacts` event after finalization.
      const artifacts = event.artifacts ?? thread.artifacts ?? [];
      return {
        ...withThread(state, id, {
          ...thread,
          run: 'finished',
          artifacts,
          artifactsError: null,
          turns: pushTurn(settle(thread.turns), {
            kind: 'info',
            source: 'system',
            content: `Run complete (stop reason: ${event.stop_reason}).`,
            streaming: false,
            pending: false,
          }),
        }),
        sessions: setSessionStatus(state.sessions, id, 'completed', artifacts.length),
      };
    }

    case 'artifacts': {
      // Recorded after deliverable finalization — the final download list.
      const artifacts = event.artifacts ?? thread.artifacts ?? [];
      const status = thread.run === 'stopped' ? 'stopped' : 'completed';
      return {
        ...withThread(state, id, { ...thread, artifacts, artifactsError: null }),
        sessions: setSessionStatus(state.sessions, id, status, artifacts.length),
      };
    }

    case 'error':
      return {
        ...withThread(state, id, {
          ...thread,
          run: 'failed',
          turns: pushTurn(settle(thread.turns), {
            kind: 'error',
            source: 'system',
            content: event.content,
            streaming: false,
            pending: false,
          }),
        }),
        sessions: setSessionStatus(state.sessions, id, 'failed'),
      };

    default:
      return state;
  }
}

export function reducer(state: RunState, action: Action): RunState {
  switch (action.type) {
    case 'sessions/loaded': {
      // Keep optimistic rows that have not been replaced by a real id yet.
      const pending = state.sessions.filter((s) => isPendingId(s.id));
      return {
        ...state,
        sessions: [...pending, ...action.sessions],
        sessionsLoaded: true,
        sessionsError: null,
      };
    }

    case 'sessions/error':
      return { ...state, sessionsLoaded: true, sessionsError: action.message };

    case 'session/select': {
      const session = state.sessions.find((s) => s.id === action.id);
      let threads = state.threads;
      if (session && !state.threads[action.id]) {
        const run = runFromStatus(session.status);
        if (run !== 'idle') threads = { ...threads, [action.id]: { ...EMPTY_THREAD, run } };
      }
      return { ...state, activeId: action.id, threads };
    }

    case 'session/createStart': {
      const summary: SessionSummary = {
        id: action.tempId,
        task: action.task,
        title: sessionTitle({ task: action.task }),
        updated_at: new Date().toISOString(),
        status: 'starting',
        artifact_count: 0,
      };
      const thread: Thread = {
        ...EMPTY_THREAD,
        run: 'starting',
        conn: 'connecting',
        turns: pushTurn([], {
          kind: 'user',
          source: 'user',
          content: action.task,
          streaming: false,
          pending: false,
        }),
      };
      return {
        ...withThread(state, action.tempId, thread),
        sessions: [summary, ...state.sessions],
        activeId: action.tempId,
        composerError: null,
      };
    }

    case 'session/created': {
      const threads = { ...state.threads };
      threads[action.id] = threads[action.tempId] ?? EMPTY_THREAD;
      delete threads[action.tempId];
      return {
        ...state,
        threads,
        sessions: state.sessions.map((s) => (s.id === action.tempId ? { ...s, id: action.id } : s)),
        activeId: state.activeId === action.tempId ? action.id : state.activeId,
      };
    }

    case 'session/createFailed': {
      const threads = { ...state.threads };
      delete threads[action.tempId];
      return {
        ...state,
        threads,
        sessions: state.sessions.filter((s) => s.id !== action.tempId),
        activeId: state.activeId === action.tempId ? null : state.activeId,
        composerError: action.message,
      };
    }

    case 'socket/conn':
      return withThread(state, action.id, { ...threadOf(state, action.id), conn: action.conn });

    case 'socket/event':
      return applyEvent(state, action.id, action.event);

    case 'answer/sent': {
      const thread = threadOf(state, action.id);
      return withThread(state, action.id, {
        ...thread,
        turns: pushTurn(thread.turns, {
          kind: 'user',
          source: 'user',
          content: action.content,
          streaming: false,
          pending: true,
        }),
      });
    }

    case 'run/stopped': {
      const thread = threadOf(state, action.id);
      return withThread(state, action.id, {
        ...thread,
        run: 'stopped',
        conn: 'closed',
        turns: pushTurn(settle(thread.turns), {
          kind: 'info',
          source: 'system',
          content:
            'Run stopped. Anything already written to the session folder is still downloadable.',
          streaming: false,
          pending: false,
        }),
      });
    }

    case 'artifacts/loaded':
      return withThread(state, action.id, {
        ...threadOf(state, action.id),
        artifacts: action.artifacts,
        artifactsError: null,
      });

    case 'artifacts/error':
      return withThread(state, action.id, {
        ...threadOf(state, action.id),
        artifactsError: action.message,
      });

    case 'health/loaded':
      return { ...state, health: action.health, healthError: null };

    case 'health/error':
      return { ...state, healthError: action.message };

    default:
      return state;
  }
}

/** Question text when the interviewer's latest message asks for a human answer, otherwise null. */
/** A satisfaction request that is still waiting for an answer (Feature 12). */
export function pendingFeedback(thread: Thread): string | null {
  const last = thread.turns[thread.turns.length - 1];
  return last && last.kind === 'feedback' ? last.content : null;
}

export function awaitingQuestion(thread: Thread): string | null {
  if (isTerminalRun(thread.run)) return null;
  for (let i = thread.turns.length - 1; i >= 0; i -= 1) {
    const turn = thread.turns[i];
    // The user's own turns come after a question, so once we hit one the
    // question is answered.
    if (turn.kind === 'user') return null;
    // Orchestrator chatter (planning_agent) sits between the question and the
    // user turn: keep walking rather than giving up on it.
    const question = extractQuestion(turn.content);
    if (question) return question;
  }
  return null;
}

/** Per-stage state for the run panel, derived from the agents that have spoken. */
export function stageStates(thread: Thread): Record<StageId, StageState> {
  const speakers = thread.turns.filter((t) => t.kind === 'agent').map((t) => t.source);
  return deriveStageStates(speakers, thread.run === 'finished');
}
