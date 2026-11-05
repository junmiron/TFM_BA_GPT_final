/**
 * Transcript auto-scroll rule (Copilot-style): follow the latest turn only when
 * the reader is already at/near the bottom, so scrolling up to read history is
 * never hijacked by a new agent message. A pending question always scrolls,
 * because the question is the thing that needs attention.
 */
export function shouldFollowLatest(
  scrollHeight: number,
  scrollTop: number,
  clientHeight: number,
  questionPending: boolean,
  threshold = 160,
): boolean {
  if (questionPending) return true;
  return scrollHeight - scrollTop - clientHeight < threshold;
}
