// Wire contract shared with the FastAPI backend. Do not extend without the backend.

export interface HealthResponse {
  status: string;
  /** Lane names (array) or a map of lane name to its model/config value. */
  lanes: Record<string, unknown> | string[];
  simulate_human: boolean;
  /** Turn cap the pipeline will hard-stop at (MAX_MESSAGES). */
  max_messages?: number;
}

export interface SessionSummary {
  id: string;
  task: string;
  /** First heading of the task/spec, for the rail. Falls back to `task`. */
  title?: string;
  updated_at: string;
  status: string;
  artifact_count: number;
  messages?: number;
}

export interface Artifact {
  name: string;
  kind: string;
  size: number;
  url: string;
}

export interface ServerInfoEvent {
  type: 'info';
  content: string;
}
export interface ServerAnswerEvent {
  type: 'answer';
  content: string;
}
export interface ServerMessageEvent {
  type: 'message';
  source: string;
  content: string;
}
export interface ServerChunkEvent {
  type: 'chunk';
  source: string;
  content: string;
}
export interface ServerCompleteEvent {
  type: 'complete';
  stop_reason: string;
  artifacts: Artifact[];
}
export interface ServerErrorEvent {
  type: 'error';
  content: string;
}

export type ServerEvent =
  | ServerInfoEvent
  | ServerAnswerEvent
  | ServerMessageEvent
  | ServerChunkEvent
  | ServerCompleteEvent
  | ServerErrorEvent;

export interface ClientAnswerEvent {
  type: 'answer';
  content: string;
}
