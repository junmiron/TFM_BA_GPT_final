import { describe, it, expect } from 'vitest';
import {
  clampSpeed,
  computeOffsets,
  firstNotDue,
  parseEvents,
  remapArtifacts,
  totalSpan,
  formatDuration,
} from './replay';
import type { ReplayEvent } from './replay';

const T0 = '2026-11-08T10:00:00.000Z';
const mk = (type: string, seconds: number, extra: Record<string, unknown> = {}): ReplayEvent => ({
  type,
  ts: new Date(Date.parse(T0) + seconds * 1000).toISOString(),
  ...extra,
} as ReplayEvent);

describe('parseEvents', () => {
  it('reads JSONL lines and skips blanks', () => {
    const text = `${JSON.stringify(mk('info', 0))}\n\n${JSON.stringify(mk('message', 1, { source: 'user', content: 'hi' }))}\n`;
    const events = parseEvents(text);
    expect(events.length).toBe(2);
    expect(events[1].type).toBe('message');
  });
});

describe('computeOffsets', () => {
  it('computes millisecond offsets from the first event', () => {
    const offsets = computeOffsets([mk('info', 0), mk('info', 2.5), mk('info', 60)]);
    expect(offsets).toEqual([0, 2500, 60000]);
    expect(totalSpan(offsets)).toBe(60000);
  });
});

describe('firstNotDue', () => {
  const offsets = [0, 1000, 2000, 5000, 9000];

  it('dispatches every event whose time has passed, in order', () => {
    expect(firstNotDue(offsets, 0, 0)).toBe(1);
    expect(firstNotDue(offsets, 0, 2500)).toBe(3);
    expect(firstNotDue(offsets, 3, 4500)).toBe(3);
    expect(firstNotDue(offsets, 3, 5000)).toBe(4);
  });

  it('never rewinds: a paused or slowed clock dispatches nothing already sent', () => {
    // After reaching cursor 4, a virtual clock of 1000 ms (speed lowered) still
    // dispatches nothing from events already consumed.
    expect(firstNotDue(offsets, 4, 1000)).toBe(4);
  });

  it('stops at the end of the log', () => {
    expect(firstNotDue(offsets, 5, 1_000_000)).toBe(5);
  });
});

describe('remapArtifacts', () => {
  it('keeps only deliverables and points them at the static sample folder', () => {
    const events = [
      mk('complete', 10, {
        stop_reason: 'MaxMessageTermination',
        artifacts: [
          { name: 'functional_specification.pdf', kind: 'pdf', size: 100, url: '/api/files/sess-x/functional_specification.pdf' },
          { name: 'process_diagram_part_a1b2c3.svg', kind: 'file', size: 50, url: '/api/files/sess-x/process_diagram_part_a1b2c3.svg' },
        ],
      }),
      mk('info', 11),
    ];
    const remapped = remapArtifacts(events, '/ba-gpt/demo/');
    const artifacts = (remapped[0] as { artifacts: unknown[] }).artifacts as { url: string }[];
    expect(artifacts.length).toBe(1);
    expect(artifacts[0].url).toBe('/ba-gpt/demo/api/files/demo/functional_specification.pdf');
    expect(remapped[1].type).toBe('info');
  });
});

describe('clampSpeed', () => {
  it('rounds arbitrary input to an offered speed', () => {
    expect(clampSpeed(1)).toBe(2);
    expect(clampSpeed(5)).toBe(4);
    expect(clampSpeed(6)).toBe(8); // tie between 4 and 8 resolves to the higher speed
    expect(clampSpeed(12)).toBe(16);
    expect(clampSpeed('8')).toBe(8);
    expect(clampSpeed(undefined)).toBe(8);
  });
});

describe('formatDuration', () => {
  it('formats milliseconds as m:ss', () => {
    expect(formatDuration(0)).toBe('0:00');
    expect(formatDuration(90_000)).toBe('1:30');
    expect(formatDuration(600_000)).toBe('10:00');
  });
});
