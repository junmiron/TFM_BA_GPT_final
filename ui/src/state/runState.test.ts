import { describe, expect, it } from 'vitest';
import {
  awaitingQuestion,
  pendingFeedback,
  initialState,
  isTerminalRun,
  reducer,
  type Action,
  type RunState,
} from '../state/runState';
import type { ServerEvent } from '../lib/types';

const apply = (state: RunState, action: Action): RunState => reducer(state, action);
const event = (e: ServerEvent): Action => ({ type: 'socket/event', id: 's1', event: e });

function startedSession(): RunState {
  let state = apply(initialState, { type: 'session/createStart', tempId: 'pending-1', task: 'Build a thing' });
  state = apply(state, { type: 'session/created', tempId: 'pending-1', id: 's1' });
  return state;
}

describe('runState reducer', () => {
  it('promotes a pending session to the real id and keeps the thread', () => {
    const state = startedSession();
    expect(state.activeId).toBe('s1');
    expect(state.sessions.map((s) => s.id)).toEqual(['s1']);
    expect(state.threads['s1'].turns[0].content).toBe('Build a thing');
    expect(state.threads['pending-1']).toBeUndefined();
  });

  it('failed creation leaves no ghost session', () => {
    let state = apply(initialState, { type: 'session/createStart', tempId: 'pending-9', task: 'x' });
    state = apply(state, { type: 'session/createFailed', tempId: 'pending-9', message: 'backend down' });
    expect(state.sessions).toHaveLength(0);
    expect(state.activeId).toBeNull();
    expect(state.composerError).toBe('backend down');
  });

  it('streams chunks into one turn and settles it with the final message', () => {
    let state = startedSession();
    state = apply(state, event({ type: 'chunk', source: 'writer', content: 'Sec' }));
    state = apply(state, event({ type: 'chunk', source: 'writer', content: 'tion 1' }));
    // turns[0] is the task the user typed; the streamed agent turn is the second.
    expect(state.threads.s1.turns).toHaveLength(2);
    expect(state.threads.s1.turns[1].content).toBe('Section 1');
    expect(state.threads.s1.turns[1].streaming).toBe(true);

    state = apply(state, event({ type: 'message', source: 'writer', content: 'Section 1 complete' }));
    expect(state.threads.s1.turns).toHaveLength(2);
    expect(state.threads.s1.turns[1].streaming).toBe(false);
    expect(state.threads.s1.turns[1].content).toBe('Section 1 complete');
  });

  it('confirms an optimistic answer when the server echoes it', () => {
    let state = startedSession();
    state = apply(state, { type: 'answer/sent', id: 's1', content: 'Offline first' });
    expect(state.threads.s1.turns.at(-1)!.pending).toBe(true);
    state = apply(state, event({ type: 'answer', content: 'Offline first' }));
    expect(state.threads.s1.turns).toHaveLength(2); // optimistic + echo do not duplicate
    expect(state.threads.s1.turns.at(-1)!.pending).toBe(false);
  });

  it('shows the question only while waiting for a human answer', () => {
    let state = startedSession();
    state = apply(state, event({ type: 'message', source: 'interviewer_agent', content: 'QUESTION: Which devices?' }));
    expect(awaitingQuestion(state.threads.s1)).toBe('Which devices?');
    state = apply(state, { type: 'answer/sent', id: 's1', content: 'Android' });
    expect(awaitingQuestion(state.threads.s1)).toBeNull();
  });

  it('a completed run is terminal and carries artifacts', () => {
    let state = startedSession();
    state = apply(state, event({ type: 'complete', stop_reason: 'terminate_agent', artifacts: [{ name: 'functional_specification.pdf', kind: 'pdf', size: 10, url: '/api/files/s1/functional_specification.pdf' }] }));
    expect(isTerminalRun(state.threads.s1.run)).toBe(true);
    expect(state.threads.s1.artifacts).toHaveLength(1);
    expect(state.sessions[0].status).toBe('completed');
  });

  it('an error event fails the run', () => {
    let state = startedSession();
    state = apply(state, event({ type: 'error', content: 'model unavailable' }));
    expect(state.threads.s1.run).toBe('failed');
    expect(state.threads.s1.turns.at(-1)!.kind).toBe('error');
  });
  it('still shows the question when the orchestrator speaks in between', () => {
    let state = startedSession();
    state = apply(state, event({ type: 'message', source: 'interviewer_agent', content: 'QUESTION: How are returns handled?' }));
    state = apply(state, event({ type: 'message', source: 'planning_agent', content: '1 user : Answer the interviewer_agent\'s question.' }));
    expect(awaitingQuestion(state.threads.s1)).toBe('How are returns handled?');
    state = apply(state, { type: 'answer/sent', id: 's1', content: 'Returns are scanned at the counter.' });
    expect(awaitingQuestion(state.threads.s1)).toBeNull();
  });

  it('does not duplicate a human answer echoed by the pipeline', () => {
    let state = startedSession();
    state = apply(state, event({ type: 'message', source: 'interviewer_agent', content: 'QUESTION: Which channels?' }));
    state = apply(state, { type: 'answer/sent', id: 's1', content: 'Online and in person.' });
    state = apply(state, event({ type: 'message', source: 'user', content: 'Online and in person.' }));
    const answers = state.threads.s1.turns.filter((turn) => turn.content === 'Online and in person.');
    expect(answers).toHaveLength(1);
    expect(answers[0].pending).toBe(false);
  });

  it('complete event carries artifacts so downloads unlock', () => {
    let state = startedSession();
    state = apply(state, event({ type: 'complete', stop_reason: 'TERMINATE', artifacts: [{ name: 'functional_specification.pdf', kind: 'pdf', size: 100, url: '/api/files/s1/functional_specification.pdf' }] }));
    expect(state.threads.s1.artifacts).toHaveLength(1);
    expect(state.sessions[0].artifact_count).toBe(1);
  });

  it('a bare complete does not wipe an already-fetched artifact list', () => {
    let state = startedSession();
    state = apply(state, { type: 'artifacts/loaded', id: 's1', artifacts: [{ name: 'interview.jsonl', kind: 'json', size: 10, url: '/api/files/s1/interview.jsonl' }] });
    state = apply(state, event({ type: 'complete', stop_reason: 'TERMINATE' }));
    expect(state.threads.s1.artifacts).toHaveLength(1);
  });

  it('the artifacts event after completion sets the final download list', () => {
    let state = startedSession();
    state = apply(state, event({ type: 'complete', stop_reason: 'TERMINATE', artifacts: [] }));
    state = apply(state, event({ type: 'artifacts', artifacts: [
      { name: 'functional_specification.md', kind: 'markdown', size: 50, url: '/api/files/s1/functional_specification.md' },
      { name: 'functional_specification.pdf', kind: 'pdf', size: 600, url: '/api/files/s1/functional_specification.pdf' },
    ] }));
    expect(state.threads.s1.artifacts).toHaveLength(2);
    expect(state.sessions[0].status).toBe('completed');
    expect(state.sessions[0].artifact_count).toBe(2);
  });
});

  it('a feedback_request creates a satisfaction turn that is not a question', () => {
    let state = startedSession();
    state = apply(state, event({ type: 'feedback_request', question: 'Are you happy with the deliverables?' }));
    const turns = state.threads['s1'].turns;
    const turn = turns[turns.length - 1];
    expect(turn.kind).toBe('feedback');
    expect(awaitingQuestion(state.threads['s1'])).toBeNull();
  });
  it('pendingFeedback is true while the satisfaction request is the latest turn', () => {
    let state = reducer(initialState, { type: 'session/select', id: 's1' });
    state = apply(state, event({ type: 'feedback_request', question: 'Are you happy with the deliverables?' }));
    expect(pendingFeedback(state.threads['s1'])).toBe('Are you happy with the deliverables?');
    state = apply(state, event({ type: 'info', content: 'Thanks! 12 chunks added to the learning library.' }));
    expect(pendingFeedback(state.threads['s1'])).toBeNull();
  });
