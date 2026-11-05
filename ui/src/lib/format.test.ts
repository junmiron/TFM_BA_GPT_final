import { describe, expect, it } from 'vitest';
import {
  extractQuestion,
  formatBytes,
  formatLanes,
  formatRelativeTime,
  formatTurnBudget,
  sessionCountLabel,
  sessionTitle,
  statusLabel,
} from './format';
import { deriveStageStates } from './workflow';
import { parseServerEvent } from './api';

describe('format helpers', () => {
  it('formats byte sizes', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(3 * 1024 * 1024)).toBe('3.0 MB');
  });

  it('formats relative time', () => {
    const now = Date.parse('2026-01-01T12:00:00Z');
    expect(formatRelativeTime('2026-01-01T11:59:30Z', now)).toBe('just now');
    expect(formatRelativeTime('2026-01-01T11:50:00Z', now)).toBe('10 min ago');
    expect(formatRelativeTime('2026-01-01T09:00:00Z', now)).toBe('3 h ago');
  });

  it('labels the human lane honestly', () => {
    expect(
      formatLanes({ model_client: 'strata', model_client_tools: 'strata', human_model: 'user' }),
    ).toEqual(['strata (chat)', 'strata (tools)', 'you (human)']);
    expect(
      formatLanes({ model_client: 'strata', model_client_tools: 'strata', human_model: 'opencode' }),
    ).toEqual(['strata (chat)', 'strata (tools)', 'opencode (human)']);
  });

  it('extracts the QUESTION line', () => {
    expect(extractQuestion('Hi.\nQUESTION: Who are the users?\n')).toBe('Who are the users?');
    expect(extractQuestion('no question here')).toBeNull();
  });

  it('labels statuses', () => {
    expect(statusLabel('awaiting_answer')).toBe('Awaiting your answer');
    expect(statusLabel('done')).toBe('Done');
    expect(statusLabel('unknown')).toBe('Saved');
  });

  it('turns a task into a plain title', () => {
    expect(sessionTitle({ task: '# Laundry Shop App\n\n## 1. Overview' })).toBe('Laundry Shop App');
    expect(sessionTitle({ task: 'plain task text' })).toBe('plain task text');
    expect(sessionTitle({ title: 'Explicit title', task: '# ignored' })).toBe('Explicit title');
    expect(sessionTitle({ id: 'sess-1' })).toBe('sess-1');
  });

  it('labels the session count', () => {
    expect(sessionCountLabel(1)).toBe('1 session');
    expect(sessionCountLabel(17)).toBe('17 sessions');
  });
});

describe('workflow', () => {
  it('marks stages before the latest speaker as done', () => {
    const states = deriveStageStates(['planning_agent', 'interviewer_agent', 'summarizer_agent'], false);
    expect(states.interview).toBe('done');
    expect(states.summary).toBe('active');
    expect(states.spec).toBe('pending');
  });

  it('marks everything done when finished', () => {
    const states = deriveStageStates([], true);
    expect(Object.values(states).every((s) => s === 'done')).toBe(true);
  });
});

describe('parseServerEvent', () => {
  it('accepts contract events and rejects junk', () => {
    expect(parseServerEvent('{"type":"chunk","source":"interviewer_agent","content":"hi"}')).not.toBeNull();
    expect(parseServerEvent('{"type":"nope"}')).toBeNull();
    expect(parseServerEvent('not json')).toBeNull();
    expect(parseServerEvent(42)).toBeNull();
  });
});

describe('formatTurnBudget', () => {
  it('shows the cap the run will stop at', () => {
    expect(formatTurnBudget(12, 300)).toBe('12 of 300 turns used.');
  });
  it('singularises one turn', () => {
    expect(formatTurnBudget(1, null)).toBe('1 turn used.');
  });
  it('says nothing is used before the run starts', () => {
    expect(formatTurnBudget(0, 300)).toBe('No turns used yet.');
  });
});
