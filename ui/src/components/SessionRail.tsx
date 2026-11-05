import { useState, type FormEvent, type KeyboardEvent } from 'react';
import { Badge, type BadgeTone } from './ui/Badge';
import { Button } from './ui/Button';
import { PlusIcon } from './ui/icons';
import { formatRelativeTime, sessionCountLabel, sessionTitle, statusLabel } from '../lib/format';
import type { SessionSummary } from '../lib/types';

export interface SessionRailProps {
  sessions: SessionSummary[];
  loaded: boolean;
  error: string | null;
  activeId: string | null;
  composerError: string | null;
  starting: boolean;
  onSelect: (id: string) => void;
  onStart: (task: string) => void;
  onRetry: () => void;
}

const STATUS_TONE: Record<string, BadgeTone> = {
  completed: 'success',
  done: 'success',
  running: 'info',
  starting: 'info',
  awaiting_answer: 'warning',
  failed: 'danger',
  stopped: 'neutral',
  unknown: 'neutral',
};

export function statusTone(status: string): BadgeTone {
  return STATUS_TONE[status] ?? 'neutral';
}

/** Left rail: new-session composer on top, session list below. */
export function SessionRail({
  sessions,
  loaded,
  error,
  activeId,
  composerError,
  starting,
  onSelect,
  onStart,
  onRetry,
}: SessionRailProps) {
  return (
    <aside aria-label="Sessions" className="flex min-h-0 flex-col gap-4">
      <Composer error={composerError} starting={starting} onStart={onStart} />

      <section aria-labelledby="sessions-heading" className="flex min-h-0 flex-1 flex-col">
        <div className="mb-2 flex items-center justify-between">
          <h2 id="sessions-heading" className="text-sm font-semibold text-foreground">
            Sessions
          </h2>
          <span className="text-xs text-muted-foreground" aria-live="polite">
            {loaded ? sessionCountLabel(sessions.length) : ''}
          </span>
        </div>

        {error && (
          <div role="alert" className="mb-2 rounded-md border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900">
            <p>Could not load sessions: {error}</p>
            <Button variant="ghost" size="sm" className="mt-1 px-0 underline" onClick={onRetry}>
              Try again
            </Button>
          </div>
        )}

        {!loaded && !error && <p className="text-sm text-muted-foreground">Loading sessions…</p>}

        {loaded && sessions.length === 0 && !error && (
          <div className="rounded-lg border border-dashed border-border bg-secondary/50 p-4 text-sm text-muted-foreground">
            <p className="font-medium text-foreground">No sessions yet</p>
            <p className="mt-1">Describe a product or process above and start your first interview.</p>
          </div>
        )}

        {sessions.length > 0 && (
          <ul
            className="max-h-80 min-h-0 space-y-2 overflow-y-auto pr-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Session list"
            tabIndex={0}
          >
            {sessions.map((session) => (
              <li key={session.id}>
                <SessionRow session={session} active={session.id === activeId} onSelect={onSelect} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </aside>
  );
}

function Composer({ error, starting, onStart }: { error: string | null; starting: boolean; onStart: (task: string) => void }) {
  const [task, setTask] = useState('');
  const canStart = task.trim().length > 0 && !starting;

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!canStart) return;
    onStart(task.trim());
    setTask('');
  };

  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form onSubmit={submit} className="rounded-lg border border-border bg-card p-3 shadow-lg" aria-labelledby="composer-heading">
      <h2 id="composer-heading" className="mb-2 text-sm font-semibold text-foreground">
        New session
      </h2>
      <label htmlFor="task-input" className="mb-1 block text-xs font-medium text-muted-foreground">
        Session goal
      </label>
      <textarea
        id="task-input"
        value={task}
        onChange={(e) => setTask(e.target.value)}
        onKeyDown={onKey}
        rows={3}
        maxLength={4000}
        required
        aria-describedby="task-hint"
        placeholder="Describe the product, users and interview goal"
        className="w-full resize-y rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
      <div className="mt-2 flex items-center justify-between gap-2">
        <span id="task-hint" className="text-xs text-muted-foreground">
          <kbd className="rounded border border-border bg-secondary px-1 py-0.5 font-mono text-[10px]">Ctrl</kbd>
          {' / '}
          <kbd className="rounded border border-border bg-secondary px-1 py-0.5 font-mono text-[10px]">⌘</kbd>
          {' + '}
          <kbd className="rounded border border-border bg-secondary px-1 py-0.5 font-mono text-[10px]">Enter</kbd>
          {' to start'}
        </span>
        <Button type="submit" variant="primary" size="sm" disabled={!canStart}>
          <PlusIcon />
          <span>{starting ? 'Starting…' : 'Start interview'}</span>
        </Button>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-sm text-rose-800">
          {error}
        </p>
      )}
    </form>
  );
}

function SessionRow({ session, active, onSelect }: { session: SessionSummary; active: boolean; onSelect: (id: string) => void }) {
  const pending = session.id.startsWith('pending-');
  return (
    <button
      type="button"
      onClick={() => !pending && onSelect(session.id)}
      aria-current={active ? 'true' : undefined}
      disabled={pending}
      className={`w-full rounded-lg border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-wait ${
        active ? 'border-primary bg-accent' : 'border-border bg-card hover:border-primary/40 hover:bg-secondary'
      }`}
    >
      <span className="flex items-start justify-between gap-2">
        <span className="line-clamp-2 block text-sm font-medium text-foreground">{sessionTitle(session)}</span>
        {!pending && (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground">
            <path d="M9 18l6-6-6-6" />
          </svg>
        )}
      </span>
      <span className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2">
          <Badge tone={statusTone(session.status)}>{statusLabel(session.status)}</Badge>
          {session.artifact_count > 0 && (
            <span className="text-xs text-muted-foreground">{session.artifact_count} files</span>
          )}
        </span>
        <span className="text-xs text-muted-foreground">{formatRelativeTime(session.updated_at)}</span>
      </span>
    </button>
  );
}
