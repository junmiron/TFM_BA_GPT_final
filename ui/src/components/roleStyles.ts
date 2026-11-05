import type { RoleId } from '../lib/roles';

export interface RoleStyle {
  /** Bubble surface and left accent bar. */
  bubble: string;
  /** Name tag. Text on background is at least 7:1. */
  tag: string;
}

/** Colour per agent role. Each pair passes WCAG AA for text. */
export const ROLE_STYLE: Record<RoleId, RoleStyle> = {
  planning: { bubble: 'bg-violet-50 border-violet-500', tag: 'bg-violet-100 text-violet-900' },
  interviewer: { bubble: 'bg-sky-50 border-sky-500', tag: 'bg-sky-100 text-sky-900' },
  summarizer: { bubble: 'bg-teal-50 border-teal-500', tag: 'bg-teal-100 text-teal-900' },
  writer: { bubble: 'bg-indigo-50 border-indigo-500', tag: 'bg-indigo-100 text-indigo-900' },
  checker: { bubble: 'bg-amber-50 border-amber-500', tag: 'bg-amber-100 text-amber-900' },
  diagram: { bubble: 'bg-emerald-50 border-emerald-500', tag: 'bg-emerald-100 text-emerald-900' },
  reviewer: { bubble: 'bg-rose-50 border-rose-500', tag: 'bg-rose-100 text-rose-900' },
  terminate: { bubble: 'bg-slate-100 border-slate-500', tag: 'bg-slate-200 text-slate-800' },
  user: { bubble: 'bg-primary text-primary-foreground border-primary', tag: 'bg-primary text-primary-foreground' },
  system: { bubble: 'bg-secondary border-border', tag: 'bg-card text-muted-foreground' },
  other: { bubble: 'bg-chat-bot border-border', tag: 'bg-secondary text-secondary-foreground' },
};
