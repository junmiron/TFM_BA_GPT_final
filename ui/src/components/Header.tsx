import { Badge, type BadgeTone } from './ui/Badge';
import { Button } from './ui/Button';
import { DownloadIcon, StopIcon } from './ui/icons';
import type { Artifact } from '../lib/types';

export interface HeaderProps {
  lanes: string[];
  /** null while health is unknown; false when the backend is unreachable. */
  healthOk: boolean | null;
  healthError: string | null;
  specArtifact: Artifact | undefined;
  onDownloadSpec: () => void;
  downloadError: string | null;
  canStop: boolean;
  onStop: () => void;
}

/** App header: name, lane in use, spec download and stop control. */
export function Header({
  lanes,
  healthOk,
  healthError,
  specArtifact,
  onDownloadSpec,
  downloadError,
  canStop,
  onStop,
}: HeaderProps) {
  const laneTone: BadgeTone = healthOk === false ? 'danger' : 'success';
  let laneText = 'Checking backend…';
  if (healthOk === true) laneText = lanes.length > 0 ? lanes.join(' / ') : 'default';
  if (healthOk === false) laneText = healthError ?? 'Backend offline';

  return (
    <header className="border-b border-border bg-card/90 px-4 py-3 backdrop-blur sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <div
            aria-hidden="true"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-primary text-sm font-bold text-primary-foreground"
          >
            BA
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-lg font-bold leading-tight text-foreground">Business Analyst GPT</h1>
            <p className="truncate text-xs text-muted-foreground">Requirements interview to functional specification</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {canStop && <StopButton onStop={onStop} />}
          <Button
            variant="secondary"
            size="sm"
            onClick={onDownloadSpec}
            disabled={!specArtifact}
            aria-label={
              specArtifact
                ? `Download the specification for the selected session (${specArtifact.name})`
                : 'Download specification: none available yet'
            }
            title={specArtifact ? undefined : 'The specification appears once a run finishes.'}
          >
            <DownloadIcon />
            <span>Download spec</span>
          </Button>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span role="status" aria-live="polite" className="flex items-center gap-2">
          <Badge tone={laneTone}>
            {healthOk === false ? 'Backend offline' : healthOk === true ? 'Backend online' : 'Checking'}
          </Badge>
          <span className="text-xs text-muted-foreground">Model lane: {laneText}</span>
        </span>
        {canStop && <span className="text-xs text-muted-foreground">Esc stops the run</span>}
      </div>

      {downloadError && (
        <p role="alert" className="mt-2 text-sm text-rose-800">
          {downloadError}
        </p>
      )}
    </header>
  );
}

function StopButton({ onStop }: { onStop: () => void }) {
  // No focus on mount: Escape is handled globally in App.tsx, and stealing
  // focus from the composer mid-run is worse than a focused button.
  return (
    <Button variant="danger" size="sm" onClick={onStop} aria-keyshortcuts="Escape">
      <StopIcon />
      <span>Stop run</span>
    </Button>
  );
}
