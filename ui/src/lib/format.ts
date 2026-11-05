import type { HealthResponse } from './types';

/** Human-readable byte size, e.g. 1536 -> "1.5 KB". */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}

/** Relative time: "just now", "5 min ago", "3 h ago", "2 d ago". */
export function formatRelativeTime(iso: string, now: number = Date.now()): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return '—';
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  if (seconds < 45) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

export function formatClock(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

const KNOWN_STATUS: Record<string, string> = {
  running: 'Running',
  starting: 'Starting',
  awaiting_answer: 'Awaiting your answer',
  done: 'Done',
  completed: 'Done',
  failed: 'Failed',
  stopped: 'Stopped',
  unknown: 'Saved',
};

/** "awaiting_answer" -> "Awaiting your answer". */
export function statusLabel(status: string): string {
  if (KNOWN_STATUS[status]) return KNOWN_STATUS[status];
  const words = status.replace(/[_-]+/g, ' ').trim().toLowerCase();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Unknown';
}

const QUESTION_LINE = /^\s*QUESTION:\s*(.+?)\s*$/m;

/**
 * A short, human title for a session: the first Markdown heading of the task,
 * otherwise the first non-empty line. Raw Markdown never reaches the rail.
 */
export function sessionTitle(session: { title?: string; task?: string; id?: string }): string {
  const explicit = (session.title ?? '').trim();
  if (explicit) return explicit;
  for (const line of (session.task ?? '').split('\n')) {
    const text = line.trim();
    if (!text) continue;
    if (text.startsWith('#')) {
      const heading = text.replace(/^#+\s*/, '').trim();
      if (heading) return heading;
    }
    return text;
  }
  return session.id ?? 'Untitled session';
}

/** "3 sessions", "1 session" — the count is never a bare number. */
export function sessionCountLabel(count: number): string {
  return `${count} ${count === 1 ? 'session' : 'sessions'}`;
}

/** Text of the first `QUESTION:` line, or null when the message has none. */
export function extractQuestion(text: string): string | null {
  const match = QUESTION_LINE.exec(text);
  return match ? match[1] : null;
}

const LANE_LABEL: Record<string, string> = {
  model_client: 'chat',
  model_client_tools: 'tools',
  human_model: 'human',
};

/**
 * Lane labels for display: "strata (chat)", "opencode (human)". Handles both
 * the array shape and the map of lane name -> model the backend returns.
 */
export function formatLanes(lanes: HealthResponse['lanes']): string[] {
  if (Array.isArray(lanes)) return lanes.map(String);
  const out: string[] = [];
  for (const [name, value] of Object.entries(lanes)) {
    if (typeof value !== 'string' && typeof value !== 'number') continue;
    const label = LANE_LABEL[name] ?? name;
    const entry = `${value} (${label})`;
    if (!out.includes(entry)) out.push(entry);
  }
  return out;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.';
}
