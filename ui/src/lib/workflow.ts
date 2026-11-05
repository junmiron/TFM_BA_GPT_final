export type StageId =
  | 'interview'
  | 'summary'
  | 'spec'
  | 'check'
  | 'diagram'
  | 'review'
  | 'export';
export type StageState = 'pending' | 'active' | 'done';

export interface StageDef {
  id: StageId;
  label: string;
  /** Lower-case agent source names that belong to this stage. */
  agents: string[];
}

export const STAGES: StageDef[] = [
  { id: 'interview', label: 'Interview', agents: ['interviewer_agent'] },
  { id: 'summary', label: 'Summary', agents: ['summarizer_agent'] },
  { id: 'spec', label: 'Spec writing', agents: ['functional_spec_writer_agent'] },
  { id: 'check', label: 'Spec check', agents: ['functional_spec_checker_agent'] },
  { id: 'diagram', label: 'Diagram', agents: ['diagram_creator_agent'] },
  { id: 'review', label: 'Diagram review', agents: ['mermaid_code_reviewer_agent'] },
  { id: 'export', label: 'Export', agents: ['terminate_agent', 'terminate'] },
];

/** Index of the stage that owns a source, or -1 when none does (e.g. planner, user). */
export function stageIndexForSource(source: string): number {
  const key = source.toLowerCase();
  return STAGES.findIndex((stage) => stage.agents.includes(key));
}

/**
 * Derives per-stage state from the ordered speakers seen so far.
 * The latest stage-owning speaker is active; stages before it are done; the
 * rest are pending. A finished run marks every stage done.
 */
export function deriveStageStates(
  speakers: string[],
  finished: boolean,
): Record<StageId, StageState> {
  let latest = -1;
  for (const source of speakers) {
    const index = stageIndexForSource(source);
    if (index >= 0) latest = index;
  }

  const result = {} as Record<StageId, StageState>;
  STAGES.forEach((stage, index) => {
    let state: StageState = 'pending';
    if (finished) state = 'done';
    else if (index === latest) state = 'active';
    else if (index < latest) state = 'done';
    result[stage.id] = state;
  });
  return result;
}
