import { Badge } from '../../../ui/src/components/ui/Badge';
import { Button } from '../../../ui/src/components/ui/Button';
import { SPEEDS, formatDuration } from '../replay';

interface PlaybackBarProps {
  paused: boolean;
  speed: number;
  showInternal: boolean;
  elapsedMs: number;
  totalMs: number;
  finished: boolean;
  onTogglePause: () => void;
  onSpeed: (speed: number) => void;
  onShowInternal: (value: boolean) => void;
  onRestart: () => void;
}

/** Pinned control bar replacing the human answer box: pause, speed, version, restart. */
export function PlaybackBar({
  paused,
  speed,
  showInternal,
  elapsedMs,
  totalMs,
  finished,
  onTogglePause,
  onSpeed,
  onShowInternal,
  onRestart,
}: PlaybackBarProps) {
  const remainingMs = Math.max(0, totalMs - elapsedMs);
  const remainingReal = remainingMs / speed;

  return (
    <div className="sticky bottom-0 rounded-lg border border-border bg-card shadow-lg px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant={paused ? 'primary' : 'secondary'} onClick={onTogglePause} disabled={finished} aria-label={paused ? 'Resume replay' : 'Pause replay'}>
          {finished ? 'Finished' : paused ? 'Resume' : 'Pause'}
        </Button>

        <div role="group" aria-label="Playback speed" className="flex gap-1">
          {SPEEDS.map((s) => (
            <Button
              key={s}
              size="sm"
              variant={speed === s ? 'primary' : 'ghost'}
              onClick={() => onSpeed(s)}
              aria-label={`Play at ${s} times speed`}
            >
              {s}&times;
            </Button>
          ))}
        </div>

        <div role="group" aria-label="Transcript version" className="flex gap-1">
          <Button size="sm" variant={!showInternal ? 'primary' : 'ghost'} onClick={() => onShowInternal(false)}>
            Interview only
          </Button>
          <Button size="sm" variant={showInternal ? 'primary' : 'ghost'} onClick={() => onShowInternal(true)}>
            Full agent team
          </Button>
        </div>

        <Button size="sm" variant="ghost" onClick={onRestart} aria-label="Restart the demo from the beginning">
          Restart
        </Button>

        <div className="ml-auto flex items-center gap-2 min-w-[160px]">
          <div aria-hidden="true" className="h-2 w-full min-width-[80px] rounded-full bg-secondary">
            <div
              className="h-2 rounded-full bg-primary"
              style={{ width: `${totalMs > 0 ? Math.min(100, (elapsedMs / totalMs) * 100) : 0}%` }}
            />
          </div>
          <span className="text-xs text-muted-foreground" aria-live="polite">
            {finished ? 'Done' : `${formatDuration(elapsedMs)} of ${formatDuration(totalMs)} \u00b7 ~${formatDuration(remainingReal)} left at ${speed}\u00d7`}
          </span>
        </div>
      </div>
      {finished && (
        <p className="mt-2 text-xs text-muted-foreground">
          <Badge tone="success">Run complete</Badge> The artifacts are ready - open them from the panel below or the Artifacts rail.
        </p>
      )}
    </div>
  );
}
