import { API_BASE_URL, WS_BASE_URL } from './config';
import type {
  Artifact,
  ClientAnswerEvent,
  HealthResponse,
  ServerEvent,
  SessionSummary,
} from './types';

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(`Cannot reach the backend at ${API_BASE_URL}.`, 0);
  }
  if (!response.ok) {
    throw new ApiError(`Request failed (HTTP ${response.status}).`, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<HealthResponse>('/api/health'),

  async listSessions(): Promise<SessionSummary[]> {
    const body = await request<{ sessions: SessionSummary[] }>('/api/sessions');
    return body.sessions;
  },

  async createSession(task: string, transcript?: { name: string; base64: string }): Promise<string> {
    const body = await request<{ session_id: string }>('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task,
        ...(transcript ? { transcript_base64: transcript.base64, transcript_name: transcript.name } : {}),
      }),
    });
    return body.session_id;
  },

  async continueSession(sessionId: string, supplement: string): Promise<{ session_id: string; version: string; merged: string }> {
    return request<{ session_id: string; version: string; merged: string }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/continue`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ supplement }) },
    );
  },

  async stopSession(sessionId: string): Promise<void> {
    await request<{ session_id: string; status: string }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/stop`,
      { method: 'POST' },
    );
  },

  async listArtifacts(sessionId: string): Promise<Artifact[]> {
    const body = await request<{ artifacts: Artifact[] }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/artifacts`,
    );
    return body.artifacts;
  },
};

/** Download URL for an artifact (contract path /api/files/SESSION_ID/NAME). */
export function artifactUrl(sessionId: string, artifact: Artifact): string {
  return `${API_BASE_URL}/api/files/${encodeURIComponent(sessionId)}/${encodeURIComponent(artifact.name)}`;
}

/**
 * Fetches the file and saves it through an object URL, so a missing file is
 * reported as an error instead of a blank download.
 */
export async function downloadArtifact(sessionId: string, artifact: Artifact): Promise<void> {
  let response: Response;
  try {
    response = await fetch(artifactUrl(sessionId, artifact));
  } catch {
    throw new ApiError('Download unavailable: the backend could not be reached.', 0);
  }
  if (response.status === 404) {
    throw new ApiError(`Download unavailable: ${artifact.name} is not on the server.`, 404);
  }
  if (!response.ok) {
    throw new ApiError(`Download unavailable (HTTP ${response.status}).`, response.status);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = artifact.name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function sessionSocketUrl(sessionId: string): string {
  return `${WS_BASE_URL}/ws/sessions/${encodeURIComponent(sessionId)}`;
}

const SERVER_EVENT_TYPES = new Set(['info', 'answer', 'message', 'chunk', 'complete', 'error', 'artifacts', 'feedback_request']);

/** Validates an incoming WebSocket frame. Returns null for anything off-contract. */
export function parseServerEvent(raw: unknown): ServerEvent | null {
  if (typeof raw !== 'string') return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== 'object' || value === null) return null;
  const type = (value as { type?: unknown }).type;
  if (typeof type !== 'string' || !SERVER_EVENT_TYPES.has(type)) return null;
  return value as ServerEvent;
}

export function answerEvent(content: string): ClientAnswerEvent {
  return { type: 'answer', content };
}

export function stopEvent(): { type: 'stop' } {
  return { type: 'stop' };
}
/** REST satisfaction feedback - works for live and persisted sessions alike. */
export async function postFeedback(sessionId: string, satisfied: boolean, comment: string): Promise<boolean> {
  try {
    await request<{ session_id: string; status: string }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/feedback`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ satisfied, comment }) },
    );
    return true;
  } catch {
    return false;
  }
}
