/** Agent roles as shown in the transcript. Colour styling lives in components/roleStyles.ts. */
export type RoleId =
  | 'planning'
  | 'interviewer'
  | 'summarizer'
  | 'writer'
  | 'checker'
  | 'diagram'
  | 'reviewer'
  | 'terminate'
  | 'user'
  | 'system'
  | 'other';

const SOURCE_ROLE: Record<string, RoleId> = {
  planning_agent: 'planning',
  interviewer_agent: 'interviewer',
  summarizer_agent: 'summarizer',
  functional_spec_writer_agent: 'writer',
  functional_spec_checker_agent: 'checker',
  diagram_creator_agent: 'diagram',
  mermaid_code_reviewer_agent: 'reviewer',
  terminate: 'terminate',
  user: 'user',
  system: 'system',
};

export function roleForSource(source: string): RoleId {
  return SOURCE_ROLE[source.toLowerCase()] ?? 'other';
}

export const ROLE_LABEL: Record<RoleId, string> = {
  planning: 'Planner',
  interviewer: 'Interviewer',
  summarizer: 'Summarizer',
  writer: 'Spec writer',
  checker: 'Spec checker',
  diagram: 'Diagram creator',
  reviewer: 'Mermaid reviewer',
  terminate: 'Termination',
  user: 'You',
  system: 'System',
  other: 'Agent',
};
