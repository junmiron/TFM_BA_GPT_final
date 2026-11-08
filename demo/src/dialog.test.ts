import { describe, it, expect } from 'vitest';
import { pickDialog } from './components/DialogBox';
import type { Turn } from '../../ui/src/state/runState';

const turn = (id: number, kind: Turn['kind'], source: string, content: string): Turn => ({
  id, kind, source, content, streaming: false, pending: false, at: id,
});

describe('pickDialog', () => {
  it('has no dialog before any question', () => {
    expect(pickDialog([turn(1, 'user', 'user', 'launch WashLoop')])).toBeNull();
  });

  it('shows a pending question until the stakeholder answers', () => {
    const dialog = pickDialog([
      turn(1, 'user', 'user', 'launch WashLoop'),
      turn(2, 'agent', 'interviewer_agent', 'QUESTION: What is the primary purpose?'),
    ]);
    expect(dialog?.question).toBe('What is the primary purpose?');
    expect(dialog?.answer).toBeNull();
  });

  it('pairs the latest question with the answer that follows it', () => {
    const dialog = pickDialog([
      turn(1, 'agent', 'interviewer_agent', 'QUESTION: First question?'),
      turn(2, 'user', 'user', 'First answer.'),
      turn(3, 'agent', 'planning_agent', 'TASK TRACKING: interviewer: pending'),
      turn(4, 'agent', 'interviewer_agent', 'QUESTION: Second question?'),
      turn(5, 'user', 'user', 'Second answer with details.'),
    ]);
    expect(dialog?.question).toBe('Second question?');
    expect(dialog?.answer).toBe('Second answer with details.');
  });

  it('ignores agent chatter without a QUESTION line', () => {
    const dialog = pickDialog([
      turn(1, 'agent', 'summarizer_agent', 'Summary ready.'),
      turn(2, 'user', 'user', 'APPROVE SUMMARY'),
    ]);
    expect(dialog).toBeNull();
  });
});
