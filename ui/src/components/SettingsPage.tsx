import { useEffect, useState } from 'react';
import { Button } from './ui/Button';
import { Badge } from './ui/Badge';
import { api } from '../lib/api';
import type { ConfigResponse } from '../lib/types';
import { errorMessage } from '../lib/format';

interface SettingsPageProps {
  onClose: () => void;
  onSaved: (config: ConfigResponse) => void;
}

/**
 * Configuration view (Feature 8): model lanes, model IDs, keys, human
 * simulation, UI visibility and run limits. Saves to the backend whitelist,
 * which writes .env and os.environ. API key values are never fetched back.
 */
export function SettingsPage({ onClose, onSaved }: SettingsPageProps) {
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  // Local edits, keyed by the env variable name.
  const [edits, setEdits] = useState<Record<string, string | boolean | number>>({});
  const [newKeys, setNewKeys] = useState<Record<string, string>>({});

  useEffect(() => {
    api.config().then(setConfig).catch((e: unknown) => setError(errorMessage(e)));
  }, []);

  if (!config) {
    return (
      <section className="mx-auto max-w-[900px] p-6">
        <h2 className="text-lg font-bold text-foreground">Configuration</h2>
        <p className="text-sm text-muted-foreground">{error ?? 'Loading configuration…'}</p>
        <Button variant="secondary" size="sm" onClick={onClose}>Back to interview</Button>
      </section>
    );
  }

  const edit = (name: string, value: string | boolean | number) => setEdits((prev) => ({ ...prev, [name]: value }));

  const save = async () => {
    const payload: Record<string, string | boolean | number> = { ...edits };
    for (const [env, value] of Object.entries(newKeys)) {
      if (value.trim()) payload[env] = value.trim();
    }
    if (Object.keys(payload).length === 0) {
      setSavedMessage('Nothing to save.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await api.saveConfig(payload);
      setConfig(updated);
      setEdits({});
      setNewKeys({});
      setSavedMessage('Saved. Model lanes apply to the next session you start; UI flags apply immediately.');
      onSaved(updated);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const profileNames = config.profiles.map((p) => p.name);

  return (
    <section className="mx-auto max-w-[900px] p-6">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-lg font-bold text-foreground">Configuration</h2>
        <Button variant="secondary" size="sm" onClick={onClose}>Back to interview</Button>
      </div>

      <div className="grid gap-4">
        <fieldset className="rounded-lg border border-border bg-card p-4">
          <legend className="mb-2 text-sm font-semibold text-foreground">Model lanes</legend>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="text-xs text-muted-foreground">
              Reasoning lane (MODEL_CLIENT)
              <select
                className="mt-1 w-full rounded-md border border-input bg-card px-2 py-2 text-sm"
                value={String(edits.MODEL_CLIENT ?? config.lanes.model_client)}
                onChange={(e) => edit('MODEL_CLIENT', e.target.value)}
              >
                {profileNames.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <label className="text-xs text-muted-foreground">
              Tool lane (MODEL_CLIENT_TOOLS)
              <select
                className="mt-1 w-full rounded-md border border-input bg-card px-2 py-2 text-sm"
                value={String(edits.MODEL_CLIENT_TOOLS ?? config.lanes.model_client_tools)}
                onChange={(e) => edit('MODEL_CLIENT_TOOLS', e.target.value)}
              >
                {profileNames.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <label className="text-xs text-muted-foreground">
              Human-simulation lane (HUMAN_MODEL)
              <select
                className="mt-1 w-full rounded-md border border-input bg-card px-2 py-2 text-sm"
                value={String(edits.HUMAN_MODEL ?? config.lanes.human_model)}
                onChange={(e) => edit('HUMAN_MODEL', e.target.value)}
              >
                {profileNames.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
          </div>
          <label className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={Boolean(edits.SIMULATE_HUMAN ?? config.simulate_human)}
              onChange={(e) => edit('SIMULATE_HUMAN', e.target.checked)}
            />
            AI-simulated human interviewer (off: you answer the interview yourself)
          </label>
        </fieldset>

        <fieldset className="rounded-lg border border-border bg-card p-4">
          <legend className="mb-2 text-sm font-semibold text-foreground">Model IDs and endpoints</legend>
          <p className="mb-2 text-xs text-muted-foreground">
            Optional per-profile overrides (&lt;PROFILE&gt;_MODEL / &lt;PROFILE&gt;_BASE_URL). Local
            services need no key.
          </p>
          <div className="grid gap-2">
            {config.profiles.map((p) => {
              const key = String(edits[`${p.name.toUpperCase()}_MODEL`] ?? p.model_override ?? '');
              const url = String(edits[`${p.name.toUpperCase()}_BASE_URL`] ?? p.base_url_override ?? '');
              return (
                <div key={p.name} className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-semibold text-foreground">{p.name}</span>
                  {p.needs_key && (
                    <Badge tone={p.key_present ? 'success' : 'danger'}>
                      {p.key_present ? 'key set' : 'key missing'}
                    </Badge>
                  )}
                  <input
                    aria-label={`${p.name} model id`}
                    placeholder="model id (from profile YAML)"
                    value={key}
                    onChange={(e) => edit(`${p.name.toUpperCase()}_MODEL`, e.target.value)}
                    className="rounded-md border border-input bg-card px-2 py-1.5 text-sm"
                  />
                  <input
                    aria-label={`${p.name} base url`}
                    placeholder="base url (optional)"
                    value={url}
                    onChange={(e) => edit(`${p.name.toUpperCase()}_BASE_URL`, e.target.value)}
                    className="rounded-md border border-input bg-card px-2 py-1.5 text-sm"
                  />
                </div>
              );
            })}
          </div>
        </fieldset>

        <fieldset className="rounded-lg border border-border bg-card p-4">
          <legend className="mb-2 text-sm font-semibold text-foreground">API keys</legend>
          <p className="mb-2 text-xs text-muted-foreground">
            Values are never shown back, only whether they are set. Type a new value to replace it.
          </p>
          <div className="grid gap-2">
            {config.keys.map((k) => (
              <div key={k.env} className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-semibold text-foreground">{k.env}</span>
                <Badge tone={k.present ? 'success' : 'neutral'}>{k.present ? 'set' : 'not set'}</Badge>
                <input
                  type="password"
                  autoComplete="new-password"
                  aria-label={`new value for ${k.env} (kept in .env, never displayed)`}
                  placeholder="enter new key value to replace"
                  value={newKeys[k.env] ?? ''}
                  onChange={(e) => setNewKeys((prev) => ({ ...prev, [k.env]: e.target.value }))}
                  className="rounded-md border border-input bg-card px-2 py-1.5 text-sm"
                />
              </div>
            ))}
          </div>
        </fieldset>

        <fieldset className="rounded-lg border border-border bg-card p-4">
          <legend className="mb-2 text-sm font-semibold text-foreground">Interface visibility</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={Boolean(edits.UI_SHOW_ARTIFACTS ?? config.ui.show_artifacts)}
                onChange={(e) => edit('UI_SHOW_ARTIFACTS', e.target.checked)}
              />
              Show Artifacts panel
            </label>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={Boolean(edits.UI_SHOW_INTERNAL_MESSAGES ?? config.ui.show_internal)}
                onChange={(e) => edit('UI_SHOW_INTERNAL_MESSAGES', e.target.checked)}
              />
              Show internal agent messages
            </label>
          </div>
        </fieldset>

        <fieldset className="rounded-lg border border-border bg-card p-4">
          <legend className="mb-2 text-sm font-semibold text-foreground">Run limits</legend>
          <div className="grid gap-3 sm:grid-cols-4">
            <label className="text-xs text-muted-foreground">
              Max messages
              <input
                type="number" min={1} max={1000}
                value={String(edits.MAX_MESSAGES ?? config.limits.max_messages)}
                onChange={(e) => edit('MAX_MESSAGES', Number(e.target.value))}
                className="mt-1 w-full rounded-md border border-input bg-card px-2 py-1.5 text-sm"
              />
            </label>
            <label className="text-xs text-muted-foreground">
              Checker rounds
              <input
                type="number" min={0} max={20}
                value={String(edits.MAX_CHECKER_ROUNDS ?? config.limits.max_checker_rounds)}
                onChange={(e) => edit('MAX_CHECKER_ROUNDS', Number(e.target.value))}
                className="mt-1 w-full rounded-md border border-input bg-card px-2 py-1.5 text-sm"
              />
            </label>
            <label className="text-xs text-muted-foreground">
              Feedback timeout (s)
              <input
                type="number" min={30} max={3600}
                value={String(edits.FEEDBACK_TIMEOUT_S ?? config.limits.feedback_timeout_s)}
                onChange={(e) => edit('FEEDBACK_TIMEOUT_S', Number(e.target.value))}
                className="mt-1 w-full rounded-md border border-input bg-card px-2 py-1.5 text-sm"
              />
            </label>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={Boolean(edits.FEEDBACK_ENABLED ?? config.limits.feedback_enabled)}
                onChange={(e) => edit('FEEDBACK_ENABLED', e.target.checked)}
              />
              Feedback learning enabled
            </label>
          </div>
        </fieldset>

        {error && <p role="alert" className="text-sm text-rose-800">{error}</p>}
        {savedMessage && <p role="status" className="text-sm text-emerald-800">{savedMessage}</p>}

        <div className="flex gap-2">
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save configuration'}
          </Button>
        </div>
      </div>
    </section>
  );
}
