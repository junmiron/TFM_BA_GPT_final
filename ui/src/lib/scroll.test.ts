import { describe, expect, it } from 'vitest';
import { shouldFollowLatest } from './scroll';

describe('transcript auto-scroll', () => {
  it('follows the latest turn when the reader is at the bottom', () => {
    expect(shouldFollowLatest(2000, 1900, 500, false)).toBe(true);
  });

  it('does not hijack a reader who scrolled up to read history', () => {
    expect(shouldFollowLatest(2000, 200, 500, false)).toBe(false);
  });

  it('always scrolls when a question is pending', () => {
    expect(shouldFollowLatest(2000, 0, 500, true)).toBe(true);
  });

  it('treats short transcripts (nothing to scroll) as at-bottom', () => {
    expect(shouldFollowLatest(500, 0, 500, false)).toBe(true);
  });
});
