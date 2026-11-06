import { memo } from 'react';
import { ROLE_STYLE } from './roleStyles';
import { Badge } from './ui/Badge';
import { roleForSource, ROLE_LABEL, type RoleId } from '../lib/roles';
import { formatClock } from '../lib/format';
import type { Turn } from '../state/runState';

export interface TranscriptProps {
  turns: Turn[];
  hasSession: boolean;
  busy: boolean;
  historical: boolean;
  /** Feature 2: when false, only interviewer/user conversation is rendered. */
  showInternal: boolean;
}

/** Live transcript. The log is aria-live so new turns and streamed chunks are announced. */
export function Transcript({ turns, hasSession, busy, historical, showInternal }: TranscriptProps) {
  if (!hasSession) {
    return (
      <EmptyState
        title="Start a session to begin"
        body="Enter a task in the left panel. The interviewer asks questions here and the agents draft the specification."
      />
    );
  }

  if (turns.length === 0) {
    return historical ? (
      <EmptyState
        title="No live transcript for this session"
        body="This session ran earlier, so its messages are not in this window. Its artifacts are still listed on the right."
      />
    ) : (
      <EmptyState
        title="Waiting for the first agent message"
        body="The planner is preparing the work. This usually takes a few seconds."
      />
    );
  }

  return (
    <div className="space-y-3">
      <ol
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
        aria-busy={busy}
        aria-label="Agent transcript"
        className="space-y-4"
      >
        {turns
          .filter((turn) => showInternal || isConversationTurn(turn))
          .map((turn) => (
            <li key={turn.id} className="animate-fade-in">
              <TurnBubble turn={turn} />
            </li>
          ))}
      </ol>
      {busy && <p className="text-xs text-muted-foreground">Agents are working…</p>}
    </div>
  );
}

const INTERNAL_SOURCES = new Set(['planner', 'planning_agent', 'summarizer', 'writer', 'checker', 'use_case_generator']);

function isConversationTurn(turn: Turn): boolean {
  if (turn.kind !== 'agent') return true;
  return !INTERNAL_SOURCES.has(turn.source);
}

const TurnBubble = memo(function TurnBubble({ turn }: { turn: Turn }) {
  if (turn.kind === 'feedback') {
    // The interactive prompt lives in the pinned composer box (Feature 12);
    // the transcript keeps a plain record of the request.
    return (
      <div className="rounded-md border border-primary/40 bg-accent/40 px-3 py-2 text-sm text-foreground">
        <span className="font-semibold">Feedback requested: </span>
        {turn.content}
      </div>
    );
  }
  if (turn.kind === 'info' || turn.kind === 'error') {
    const isError = turn.kind === 'error';
    return (
      <div
        role={isError ? 'alert' : undefined}
        className={`rounded-md border px-3 py-2 text-sm ${
          isError
            ? 'border-rose-300 bg-rose-50 text-rose-900'
            : 'border-border bg-secondary text-secondary-foreground'
        }`}
      >
        {isError && <span className="font-semibold">Run failed: </span>}
        {turn.content}
      </div>
    );
  }

  const role: RoleId = turn.kind === 'user' ? 'user' : roleForSource(turn.source);
  const style = ROLE_STYLE[role];
  const isUser = role === 'user';
  const bubbleText = isUser ? 'text-primary-foreground' : 'text-chat-bot-foreground';

  return (
    <article
      aria-label={`${ROLE_LABEL[role]} message at ${formatClock(turn.at)}`}
      className={`flex flex-col gap-1 ${isUser ? 'items-end' : 'items-start'}`}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge className={style.tag}>{ROLE_LABEL[role]}</Badge>
        {turn.pending && <span>Sending…</span>}
        {turn.streaming && <span>Typing…</span>}
        {!turn.streaming && !turn.pending && <span>{formatClock(turn.at)}</span>}
      </div>
      <div
        className={`max-w-[92%] whitespace-pre-wrap break-words rounded-lg border-l-4 px-4 py-3 text-sm leading-relaxed sm:max-w-[80%] ${style.bubble} ${bubbleText}`}
      >
        {turn.content}
      </div>
    </article>
  );
});


function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex min-h-[16rem] flex-col items-center justify-center rounded-lg border border-dashed border-border bg-secondary/40 p-8 text-center">
      <p className="text-base font-semibold text-foreground">{title}</p>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">{body}</p>
    </div>
  );
}
