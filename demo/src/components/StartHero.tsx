import { Panel } from '../../../ui/src/components/ui/Panel';
import { Button } from '../../../ui/src/components/ui/Button';
import type { ReplayMeta } from '../replay';

interface StartHeroProps {
  meta: ReplayMeta;
  onStart: () => void;
  loading: boolean;
  error: string | null;
}

/** Landing state: the fixed goal, a one-button start, nothing else interactive. */
export function StartHero({ meta, onStart, loading, error }: StartHeroProps) {
  const duration = meta.wall_duration_s ? `${Math.round(meta.wall_duration_s / 60)} min` : 'about an hour';
  return (
    <main id="main" className="mx-auto max-w-[640px] px-4 py-10">
      <Panel className="animate-fade-in">
        <div className="p-6">
          <h1 className="text-lg font-semibold text-foreground">Watch an AI business analyst run a real interview</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            This is a scripted replay of a genuine end-to-end run: the interviewer asks questions,
            a simulated stakeholder answers, and the agent team writes the functional specification.
            Everything is the real UI - you can pause, change the speed and switch the internal
            agent messages on and off while it runs.
          </p>

          <div className="mt-4 rounded-md border border-border bg-secondary/60 p-4">
            <p className="text-xs font-semibold text-muted-foreground">Fixed goal of this session</p>
            <p className="mt-2 whitespace-pre-wrap text-sm text-foreground">{meta.task}</p>
          </div>

          <p className="mt-3 text-xs text-muted-foreground">
            Real run took {duration} with {meta.event_count ?? 0} events
            ({meta.event_counts?.message ?? 0} agent messages, {meta.event_counts?.answer ?? 0} stakeholder answers).
            Start at 8&times; to watch it in a few minutes.
          </p>

          {error ? (
            <p role="alert" className="mt-3 rounded-md border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900">
              {error}
            </p>
          ) : (
            <Button className="mt-5" variant="primary" onClick={onStart} disabled={loading}>
              {loading ? 'Loading the session\u2026' : 'Start interview'}
            </Button>
          )}
        </div>
      </Panel>
    </main>
  );
}
