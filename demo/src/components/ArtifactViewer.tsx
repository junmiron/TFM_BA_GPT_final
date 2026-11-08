import { useState } from 'react';
import { Panel } from '../../../ui/src/components/ui/Panel';
import { Button } from '../../../ui/src/components/ui/Button';
import { formatBytes } from '../../../ui/src/lib/format';
import { findHtmlArtifact, findPdfArtifact, sortArtifacts } from '../../../ui/src/lib/artifacts';
import type { Artifact } from '../../../ui/src/lib/types';

interface ArtifactViewerProps {
  artifacts: Artifact[];
}

/** End-of-run showcase: the deliverables from the recorded session, viewable
 * inline straight from the static site - the same files committed under
 * examples/sample_session/ and linked from the portfolio page. */
export function ArtifactViewer({ artifacts }: ArtifactViewerProps) {
  const sorted = sortArtifacts(artifacts);
  const pdf = findPdfArtifact(artifacts);
  const html = findHtmlArtifact(artifacts);
  const [preview, setPreview] = useState<string | null>(null);

  return (
    <Panel title="Deliverables" headingId="deliverables-heading" className="animate-fade-in">
      <div className="p-4">
        <div className="flex flex-wrap gap-2">
          {html && (
            <Button variant="primary" onClick={() => setPreview(html.url)}>
              View the interactive spec
            </Button>
          )}
          {pdf && (
            <Button variant="secondary" onClick={() => setPreview(pdf.url)}>
              Preview the PDF
            </Button>
          )}
        </div>
        <ul className="mt-3 divide-y divide-border">
          {sorted.map((artifact) => (
            <li key={artifact.name} className="flex items-center justify-between gap-3 py-2">
              <span className="min-w-0 truncate text-sm text-foreground" title={artifact.name}>
                {artifact.name}
              </span>
              <span className="text-xs text-muted-foreground">
                {artifact.kind} &middot; {formatBytes(artifact.size)}
              </span>
            </li>
          ))}
        </ul>
        {preview && (
          <div className="mt-4">
            <iframe
              src={preview}
              title="Deliverable preview"
              className="w-full h-[520px] rounded-md border border-border bg-white"
              loading="lazy"
            />
            <p className="mt-2 text-xs text-muted-foreground">
              <a href={preview} target="_blank" rel="noopener">Open in a new tab &#8600;</a>
            </p>
          </div>
        )}
      </div>
    </Panel>
  );
}
