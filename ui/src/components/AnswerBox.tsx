import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { Button } from './ui/Button';
import { SendIcon } from './ui/icons';

export interface AnswerBoxProps {
  question: string;
  connected: boolean;
  onSend: (answer: string) => boolean;
}

/** Inline answer box shown when the interviewer has asked a QUESTION. */
export function AnswerBox({ question, connected, onSend }: AnswerBoxProps) {
  const [answer, setAnswer] = useState('');
  const [sendError, setSendError] = useState<string | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);
  const id = useId().replace(/:/g, '-');
  const canSend = answer.trim().length > 0 && connected;

  useEffect(() => {
    ref.current?.focus({ preventScroll: false });
  }, [question]);

  const submit = () => {
    const text = answer.trim();
    if (!text) return;
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
