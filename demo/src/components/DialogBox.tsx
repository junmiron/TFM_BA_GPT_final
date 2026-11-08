import { extractQuestion } from '../../../ui/src/lib/format';
import type { Turn } from '../../../ui/src/state/runState';

export interface Dialog {
  question: string;
  answer: string | null;
}

/**
 * The pending exchange in the replay: the latest interviewer QUESTION and the
 * stakeholder answer that follows it (null while the simulated stakeholder is
 * still composing). Same extraction the product's answer box uses.
 */
export function pickDialog(turns: Turn[]): Dialog | null {
  for (let i = turns.length - 1; i >= 0; i -= 1) {
    const question = turns[i].kind === 'agent' ? extractQuestion(turns[i].content) : null;
    if (!question) continue;
    const answer = turns.slice(i + 1).find((turn) => turn.kind === 'user');
    return { question, answer: answer ? answer.content : null };
  }
  return null;
}

/** Replay counterpart of the real UI's AnswerBox: pinned question and answer. */
export function DialogBox({ turns }: { turns: Turn[] }) {
  const dialog = pickDialog(turns);

  if (!dialog) {
    return (
      <section aria-label="Interview dialog" className="rounded-lg border border-dashed border-border bg-card/60 p-4">
        <p className="text-sm text-muted-foreground">No question pending yet - the interview has not started.</p>
      </section>
    );
  }

  return (
    <section aria-label="Interview dialog" className="rounded-lg border-2 border-primary bg-accent p-4 shadow-glow">
      <div className="mb-2 flex items-center gap-2">
        <span
          aria-hidden="true"
          className={`h-2.5 w-2.5 rounded-full ${dialog.answer ? 'bg-emerald-600' : 'animate-pulse-dot bg-primary'}`}
        />
        <h3 className="text-sm font-semibold text-accent-foreground">
          {dialog.answer ? 'Simulated stakeholder answered' : 'Awaiting stakeholder answer'}
        </h3>
      </div>
      <p className="whitespace-pre-wrap text-sm text-foreground">{dialog.question}</p>
      {dialog.answer ? (
        <div className="mt-3 rounded-md border border-border bg-card p-3">
          <p className="text-xs font-semibold text-muted-foreground">Answer (opencode stakeholder lane)</p>
          <p className="mt-1 whitespace-pre-wrap text-sm text-foreground">{dialog.answer}</p>
        </div>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">The stakeholder lane is composing the reply&hellip;</p>
      )}
    </section>
  );
}
