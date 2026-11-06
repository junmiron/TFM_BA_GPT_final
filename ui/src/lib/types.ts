// Wire contract shared with the FastAPI backend. Do not extend without the backend.

export interface HealthResponse {
  status: string;
  /** Feature 1: satisfaction gate on/off (FEEDBACK_ENABLED). */
  feedback_enabled?: boolean;
  /** Feature 2: UI visibility switches from .env. */
  ui?: { show_artifacts?: boolean; show_internal?: boolean };
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
  /** Artifact list as of completion; a follow-up `artifacts` event carries the final list. */
  artifacts?: Artifact[];
}
export interface ServerArtifactsEvent {
  type: 'artifacts';
  artifacts: Artifact[];
}
export interface ServerErrorEvent {
  type: 'error';
  content: string;
}
export interface ServerFeedbackRequestEvent {
  type: 'feedback_request';
  question: string;
}

export type ServerEvent =
  | ServerInfoEvent
  | ServerAnswerEvent
  | ServerMessageEvent
  | ServerChunkEvent
  | ServerCompleteEvent
  | ServerArtifactsEvent
  | ServerErrorEvent
  | ServerFeedbackRequestEvent;

export interface ClientAnswerEvent {
  type: 'answer';
  content: string;
}
export interface ClientFeedbackEvent {
  type: 'feedback';
  satisfied: boolean;
  comment?: string;
}
