/**
 * Transcript auto-scroll rule (Copilot-style): follow the latest turn only when
 * the reader is already at/near the bottom, so scrolling up to read history is
 * never hijacked by a new agent message. Pending attention (a question or the satisfaction request) always
 * scrolls, because those are the things that need the reader's eyes.
 */
export function shouldFollowLatest(
  scrollHeight: number,
  scrollTop: number,
  clientHeight: number,
  attentionPending: boolean,
  threshold = 160,
): boolean {
  if (attentionPending) return true;
  return scrollHeight - scrollTop - clientHeight < threshold;
}
