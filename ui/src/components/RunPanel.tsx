import { useState } from 'react';
import { Panel } from './ui/Panel';
import { Badge, type BadgeTone } from './ui/Badge';
import { Button } from './ui/Button';
import { DownloadIcon, FileIcon } from './ui/icons';
import { STAGES, type StageId, type StageState } from '../lib/workflow';
import { formatBytes } from '../lib/format';
import { downloadArtifact } from '../lib/api';
import { sortArtifacts } from '../lib/artifacts';
import { errorMessage } from '../lib/format';
import type { Artifact } from '../lib/types';

export interface RunPanelProps {
  sessionId: string | null;
  stages: Record<StageId, StageState>;
  runActive: boolean;
  artifacts: Artifact[] | null;
  artifactsError: string | null;
  onRetryArtifacts: () => void;
}

const STAGE_TONE: Record<StageState, BadgeTone> = { done: 'success', active: 'info', pending: 'neutral' };
const STAGE_TEXT: Record<StageState, string> = { done: 'Done', active: 'In progress', pending: 'Not started' };

/** Right rail: workflow progress and downloadable artifacts. */
export function RunPanel({ sessionId, stages, runActive, artifacts, artifactsError, onRetryArtifacts }: RunPanelProps) {
  return (
    <aside aria-label="Run progress" className="flex min-h-0 flex-col gap-4">
      <Panel title="Workflow" headingId="workflow-heading">
        <ol aria-labelledby="workflow-heading" className="space-y-2 p-4">
          {STAGES.map((stage) => {
            const state = stages[stage.id];
            return (
              <li key={stage.id} className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-2 text-sm text-foreground">
                  <StageMarker state={state} />
                  <span>{stage.label}</span>
                </span>
                <Badge tone={STAGE_TONE[state]}>
                  <span className="sr-only">Status: </span>
                  {STAGE_TEXT[state]}
                </Badge>
              </li>
            );
          })}
        </ol>
        <p className="px-4 pb-4 text-xs text-muted-foreground">
          {sessionId ? (runActive ? 'Stages update as each agent speaks.' : 'Run is not active.') : 'Stages light up once a run starts.'}
        </p>
      </Panel>

      <Panel title="Artifacts" headingId="artifacts-heading">
        <ArtifactsBody
          sessionId={sessionId}
          artifacts={artifacts}
          error={artifactsError}
          runActive={runActive}
          onRetry={onRetryArtifacts}
        />
      </Panel>
    </aside>
  );
}

function StageMarker({ state }: { state: StageState }) {
  if (state === 'done') {
    return (
      <span aria-hidden="true" className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-700 text-[10px] font-bold text-white">
        ✓
      </span>
    );
  }
  if (state === 'active') {
    return <span aria-hidden="true" className="h-3 w-3 animate-pulse-dot rounded-full bg-primary" />;
  }
  return <span aria-hidden="true" className="h-3 w-3 rounded-full border-2 border-muted-foreground" />;
}

function ArtifactsBody({
  sessionId,
  artifacts,
  error,
  runActive,
  onRetry,
}: {
  sessionId: string | null;
  artifacts: Artifact[] | null;
  error: string | null;
  runActive: boolean;
  onRetry: () => void;
}) {
  if (!sessionId) return <EmptyArtifacts text="Artifacts appear here when a run completes." />;
  if (error) {
    return (
      <div role="alert" className="m-4 rounded-md border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900">
        <p>Could not load artifacts: {error}</p>
        <Button variant="ghost" size="sm" className="mt-1 px-0 underline" onClick={onRetry}>
          Try again
        </Button>
      </div>
    );
  }
  if (artifacts === null) return <p className="p-4 text-sm text-muted-foreground">Loading artifacts…</p>;
  if (artifacts.length === 0) {
    return (
      <EmptyArtifacts
        text={runActive ? 'Files will appear here once the run completes.' : 'This session has no artifacts yet.'}
      />
    );
  }
  return <ArtifactList sessionId={sessionId} artifacts={sortArtifacts(artifacts)} />;
}

function EmptyArtifacts({ text }: { text: string }) {
  return (
    <div className="m-4 rounded-lg border border-dashed border-border bg-secondary/40 p-4 text-center text-sm text-muted-foreground">
      <FileIcon className="mx-auto mb-2 text-muted-foreground" />
      {text}
    </div>
  );
}

function ArtifactList({ sessionId, artifacts }: { sessionId: string; artifacts: Artifact[] }) {
  return (
    <ul className="divide-y divide-border" aria-label="Downloadable artifacts">
      {artifacts.map((artifact) => (
        <li key={artifact.name}>
          <ArtifactRow sessionId={sessionId} artifact={artifact} />
        </li>
      ))}
    </ul>
  );
}

function ArtifactRow({ sessionId, artifact }: { sessionId: string; artifact: Artifact }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const download = async () => {
    setBusy(true);
    setError(null);
    try {
      await downloadArtifact(sessionId, artifact);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-foreground" title={artifact.name}>
          {artifact.name}
        </p>
        <p className="text-xs text-muted-foreground">
          {artifact.kind} · {formatBytes(artifact.size)}
        </p>
        {error && (
          <p role="alert" className="mt-1 text-xs text-rose-800">
            {error}
          </p>
        )}
      </div>
      <Button
        variant="secondary"
        size="sm"
        onClick={download}
        disabled={busy}
        aria-label={`Download ${artifact.name}, ${formatBytes(artifact.size)}`}
      >
        <DownloadIcon />
        <span>{busy ? 'Downloading…' : 'Download'}</span>
      </Button>
    </div>
  );
}
