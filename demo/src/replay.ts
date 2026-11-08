/**
 * Replay engine for the interactive Vercel demo.
 *
 * The demo replays a recorded, real BA-GPT run: exactly the event stream the
 * FastAPI backend broadcasts over the session WebSocket (info/answer/message/
 * chunk/complete/artifacts), captured to events.jsonl with real UTC
 * timestamps. A virtual clock advances at `speed`x, and events become due when
 * their recorded offset is reached. The product UI's reducer (ui/src/state/
 * runState.ts) turns those events into transcript turns, stage badges and the
 * artifact list - the demo reuses that code, it does not mock it.
 */
import type { Artifact } from '../../ui/src/lib/types';

/** Wire shape of a recorded event: the server event fields plus its timestamp. */
export interface ReplayEvent {
  type: string;
  ts: string;
  content?: string;
  source?: string;
  stop_reason?: string;
  artifacts?: Artifact[];
  question?: string;
}

export interface ReplayMeta {
  session_id?: string;
  task: string;
  lanes?: Record<string, string>;
  started_at?: string;
  ended_at?: string;
  wall_duration_s?: number;
  event_count?: number;
  event_counts?: Record<string, number>;
  sources?: string[];
  stop_reason?: string;
  error?: string | null;
}

export interface ReplayData {
  events: ReplayEvent[];
  /** Milliseconds from the first event to each event. */
  offsets: number[];
  meta: ReplayMeta;
}

/** Deliverables the demo offers. Everything the pipeline writes besides
 * these (fragment caches, band PNGs, intermediates) stays out of the UI. */
export const SAMPLE_FILES = new Set([
  'functional_specification.pdf',
  'functional_specification.html',
  'functional_specification.md',
  'functional_specification.formatted.md',
  'interview.jsonl',
  'canvas_diagram.md',
  'process_diagram.mmd',
  'process_diagram.png',
  'process_diagram.svg',
  'process_diagram_2.mmd',
  'process_diagram_2.png',
  'process_diagram_2.svg',
  'process_diagram_3.mmd',
  'process_diagram_3.png',
  'process_diagram_3.svg',
  'process_diagram_4.mmd',
  'process_diagram_4.png',
  'process_diagram_4.svg',
]);

export const SPEEDS = [2, 4, 8, 16] as const;
export const DEFAULT_SPEED = 8;

export function clampSpeed(value: unknown): number {
  if (value === null || value === undefined || value === '') return DEFAULT_SPEED;
  const number = Number(value);
  if (!Number.isFinite(number)) return DEFAULT_SPEED;
  const target = Math.min(Math.max(number, SPEEDS[0]), SPEEDS[SPEEDS.length - 1]);
  return SPEEDS.reduce((best, s) => {
    const d = Math.abs(s - target);
    const dBest = Math.abs(best - target);
    return d < dBest || (d === dBest && s > best) ? s : best;
  }, SPEEDS[0]);
}

export function parseEvents(text: string): ReplayEvent[] {
  const events: ReplayEvent[] = [];
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const value = JSON.parse(trimmed) as ReplayEvent;
    if (!value || typeof value.type !== 'string' || typeof value.ts !== 'string') continue;
    events.push(value);
  }
  return events;
}

export function computeOffsets(events: ReplayEvent[]): number[] {
  if (events.length === 0) return [];
  const t0 = Date.parse(events[0].ts);
  return events.map((event) => Math.max(0, Date.parse(event.ts) - t0));
}

export function totalSpan(offsets: number[]): number {
  return offsets.length === 0 ? 0 : offsets[offsets.length - 1];
}

/**
 * Index of the first event whose offset is still in the future at `virtualMs`.
 * All events from `cursor` up to (but not including) the returned index are
 * due and should be dispatched, preserving order - chunk bursts replay as
 * typing, and the closing `message` event settles the streamed turn.
 */
export function firstNotDue(offsets: number[], cursor: number, virtualMs: number): number {
  let index = cursor;
  while (index < offsets.length && offsets[index] <= virtualMs) index += 1;
  return index;
}

/** Rewrite artifact lists so downloads resolve to the static sample files
 * served under <base>api/files/demo/<name> (the same contract the product
 * UI builds from API_BASE_URL). */
export const DEMO_ARTIFACT_DIR = 'api/files/demo';

export function remapArtifacts(events: ReplayEvent[], baseUrl: string): ReplayEvent[] {
  const sampleUrl = (name: string) => `${baseUrl}${DEMO_ARTIFACT_DIR}/${name}`;
  return events.map((event) => {
    if (event.type !== 'complete' && event.type !== 'artifacts') return event;
    const artifacts: Artifact[] = Array.isArray(event.artifacts) ? event.artifacts : [];
    const kept = artifacts
      .filter((artifact) => SAMPLE_FILES.has(artifact.name))
      .map((artifact) => ({ ...artifact, url: sampleUrl(artifact.name) }));
    return { ...event, artifacts: kept };
  });
}

/** The pipeline echoes stakeholder answers as "🧣 Stakeholder: ..." - the UI
 * already labels the turn as "You", so the prefix is redundant in the demo. */
export function normalizeAnswers(events: ReplayEvent[]): ReplayEvent[] {
  const prefix = "🧣 Stakeholder: ";
  return events.map((event) =>
    event.type === "answer" && event.content && event.content.startsWith(prefix)
      ? { ...event, content: event.content.slice(prefix.length) }
      : event
  );
}

export async function loadReplay(): Promise<ReplayData> {
  const base = import.meta.env.BASE_URL || '/';
  const metaResponse = await fetch(`${base}meta.json`);
  if (!metaResponse.ok) throw new Error(`Could not load meta.json (HTTP ${metaResponse.status}).`);
  const meta = (await metaResponse.json()) as ReplayMeta;
  const eventsResponse = await fetch(`${base}events.jsonl`);
  if (!eventsResponse.ok) throw new Error(`Could not load events.jsonl (HTTP ${eventsResponse.status}).`);
  const events = remapArtifacts(normalizeAnswers(parseEvents(await eventsResponse.text())), base);
  if (events.length === 0) throw new Error('The replay log is empty.');
  return { events, offsets: computeOffsets(events), meta };
}

export function formatDuration(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`;
}
