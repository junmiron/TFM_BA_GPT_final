import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { Button } from './ui/Button';
import { SendIcon } from './ui/icons';

export interface AnswerBoxProps {
  /** The pending interviewer question, or null when nothing awaits an answer. */
  question: string | null;
  /** Shown instead of the question when there is none. */
  caption: string;
  connected: boolean;
  onSend: (answer: string) => boolean;
  /** Satisfaction request awaiting an answer (Feature 12); null when none. */
  feedback: string | null;
  onFeedback: (satisfied: boolean, comment: string) => void;
  /** Open items in the finished spec awaiting confirmation (persisted sessions). */
  specQuestions: string[];
  /** Route a confirmation answer into the spec via the continuation mechanism. */
  onConfirm: (answer: string) => Promise<boolean>;
}

/**
 * Interview answer box. Always on screen (never appears/disappears):
 * active when a question is pending, greyed out and disabled otherwise.
 */
export function AnswerBox({ question, caption, connected, onSend, feedback, onFeedback, specQuestions, onConfirm }: AnswerBoxProps) {
  const [answer, setAnswer] = useState('');
  const [commentOpen, setCommentOpen] = useState(false);
  const [comment, setComment] = useState('');
  const [feedbackSent, setFeedbackSent] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  const id = useId().replace(/:/g, '-');
  const canSend = Boolean(question) && answer.trim().length > 0 && connected;

  useEffect(() => {
    // Focus only when a real question arrives; the idle box must not steal focus.
    if (question) ref.current?.focus({ preventScroll: false });
  }, [question]);

  const submit = () => {
    const text = answer.trim();
    if (!text || !question) return;
    if (!connected) {
      setSendError('Not connected to the run. Your answer was not sent; it will be available once the connection returns.');
      return;
    }
    if (onSend(text)) {
      setAnswer('');
      setSendError(null);
    } else {
      setSendError('The connection dropped while sending. Please try again in a moment.');
    }
  };

  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      submit();
    }
  };

  if (!question && feedback && !feedbackSent) {
    const submitFeedback = (satisfied: boolean, note: string) => {
      if (!connected) {
        setSendError('Not connected to the run. The feedback was not sent.');
        return;
      }
      onFeedback(satisfied, note);
      setFeedbackSent(true);
      setCommentOpen(false);
      setComment('');
    };
    return (
      <section aria-labelledby={`${id}-feedback-title`} className="rounded-lg border-2 border-primary bg-accent p-4 shadow-glow">
        <div className="mb-2 flex items-center gap-2">
          <span aria-hidden="true" className="h-2.5 w-2.5 animate-pulse-dot rounded-full bg-primary" />
          <h3 id={`${id}-feedback-title`} className="text-sm font-semibold text-accent-foreground">
            Before you close this session
          </h3>
        </div>
        <p className="mb-3 whitespace-pre-wrap text-sm text-foreground">{feedback}</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" size="sm" onClick={() => submitFeedback(true, '')}>
            Yes, deliverables are good
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setCommentOpen(true)}>
            Not quite — tell us what to fix
          </Button>
        </div>
        {commentOpen && (
          <div className="mt-3">
            <label htmlFor={`${id}-comment`} className="mb-1 block text-xs font-medium text-foreground">
              What needs improvement?
            </label>
            <textarea
              id={`${id}-comment`}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              rows={3}
              maxLength={4000}
              className="w-full resize-y rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              placeholder="Describe what is missing or wrong with the deliverables…"
            />
            <div className="mt-2 flex justify-between gap-2">
              <span className="text-xs text-foreground/80">Your feedback tunes the learning library.</span>
              <Button variant="primary" size="sm" onClick={() => submitFeedback(false, comment.trim())}>
                Send feedback
              </Button>
            </div>
          </div>
        )}
        {sendError && (
          <p role="alert" className="mt-2 text-sm text-rose-800">{sendError}</p>
        )}
      </section>
    );
  }

  if (!question && specQuestions.length > 0) {
    const submitConfirm = async () => {
      const text = answer.trim();
      if (!text || confirmBusy) return;
      setConfirmBusy(true);
      setSendError(null);
      const ok = await onConfirm(text);
      setConfirmBusy(false);
      if (ok) setAnswer('');
      else setSendError('The confirmation could not be saved. Please try again.');
    };

    return (
      <section aria-labelledby={`${id}-confirm-title`} className="rounded-lg border-2 border-primary bg-accent p-4 shadow-glow">
        <div className="mb-2 flex items-center gap-2">
          <span aria-hidden="true" className="h-2.5 w-2.5 animate-pulse-dot rounded-full bg-primary" />
          <h3 id={`${id}-confirm-title`} className="text-sm font-semibold text-accent-foreground">
            Open items in the spec awaiting your confirmation ({specQuestions.length})
          </h3>
        </div>
        <ol className="mb-3 list-inside space-y-1 text-sm text-foreground">
          {specQuestions.slice(0, 5).map((q) => (
            <li key={q} className="whitespace-pre-wrap">{q}</li>
          ))}
          {specQuestions.length > 5 && (
            <li className="text-muted-foreground">+{specQuestions.length - 5} more open items</li>
          )}
        </ol>
        <label htmlFor={`${id}-confirm-input`} className="mb-1 block text-xs font-medium text-foreground">
          Your confirmations
        </label>
        <textarea
          id={`${id}-confirm-input`}
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
              event.preventDefault();
              void submitConfirm();
            }
          }}
          rows={3}
          maxLength={4000}
          className="w-full resize-y rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          placeholder="Confirm or amend these open items (you can answer several at once)…"
        />
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="text-xs text-foreground/80">Answers are merged into the spec and the PDF/HTML/MD are regenerated.</span>
          <Button variant="primary" size="sm" onClick={() => void submitConfirm()} disabled={!answer.trim() || confirmBusy}>
            <SendIcon />
            <span>{confirmBusy ? 'Updating…' : 'Send confirmation'}</span>
          </Button>
        </div>
        {sendError && (
          <p role="alert" className="mt-2 text-sm text-rose-800">{sendError}</p>
        )}
      </section>
    );
  }

  if (!question) {
    return (
      <section aria-live="polite" className="rounded-lg border border-dashed border-border bg-card/60 p-4">
        <p className="text-sm text-muted-foreground">{caption}</p>
        <textarea
          aria-disabled="true"
          disabled
          rows={3}
          className="mt-2 w-full rounded-md border border-border bg-secondary/40 px-3 py-2 text-sm text-muted-foreground"
          placeholder="No pending question"
        />
      </section>
    );
  }

  return (
    <section
      aria-labelledby={`${id}-title`}
      className="rounded-lg border-2 border-primary bg-accent p-4 shadow-glow"
    >
      <div className="mb-2 flex items-center gap-2">
        <span aria-hidden="true" className="h-2.5 w-2.5 animate-pulse-dot rounded-full bg-primary" />
        <h3 id={`${id}-title`} className="text-sm font-semibold text-accent-foreground">
          Awaiting your answer
        </h3>
      </div>
      <p className="mb-3 whitespace-pre-wrap text-sm text-foreground">{question}</p>
      <label htmlFor={`${id}-input`} className="mb-1 block text-xs font-medium text-foreground">
        Your answer
      </label>
      <textarea
        id={`${id}-input`}
        ref={ref}
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        onKeyDown={onKey}
        rows={3}
        maxLength={4000}
        aria-describedby={`${id}-hint`}
        className="w-full resize-y rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        placeholder="Type your answer…"
      />
      <div className="mt-2 flex items-center justify-between gap-2">
        <span id={`${id}-hint`} className="text-xs text-foreground/80">
          {connected ? 'Ctrl/⌘ + Enter to send' : 'Reconnecting to the run…'}
        </span>
        <Button variant="primary" size="sm" onClick={submit} disabled={!canSend}>
          <SendIcon />
          <span>Send answer</span>
        </Button>
      </div>
      {sendError && (
        <p role="alert" className="mt-2 text-sm text-rose-800">
          {sendError}
        </p>
      )}
    </section>
  );
}
