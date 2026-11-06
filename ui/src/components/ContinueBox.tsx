import { useState } from 'react';
import { Button } from './ui/Button';
import { api } from '../lib/api';
import { errorMessage } from '../lib/format';

/** Feature 3: feed extra information into an existing session's spec. */
export function ContinueBox({
  sessionId,
  onInfo,
}: {
  sessionId: string;
  onInfo: (message: string) => void;
}) {
  const [supplement, setSupplement] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const text = supplement.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.continueSession(sessionId, text);
      setSupplement('');
      onInfo(`Specification updated to ${result.version} (${result.merged} merge). Deliverables re-rendered.`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-lg border border-border bg-card p-3" aria-label="Add information to this specification">
      <h3 className="mb-1 text-sm font-semibold text-foreground">Add information to this specification</h3>
      <p className="mb-2 text-xs text-muted-foreground">
        New requirements, decisions or corrections. The spec is updated in place and the
        PDF/HTML/MD are regenerated in this session folder.
      </p>
      <label htmlFor="continue-input" className="sr-only">Supplement</label>
      <textarea
        id="continue-input"
        value={supplement}
        onChange={(e) => setSupplement(e.target.value)}
        rows={3}
        maxLength={4000}
        placeholder="What should be added to the existing specification?"
        className="w-full resize-y rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground"
      />
      <div className="mt-2 flex items-center justify-between gap-2">
        {error && <span role="alert" className="text-xs text-rose-800">{error}</span>}
        <Button variant="primary" size="sm" onClick={submit} disabled={!supplement.trim() || busy}>
          {busy ? 'Updating…' : 'Update specification'}
        </Button>
      </div>
    </section>
  );
}
