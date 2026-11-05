import { describe, expect, it } from 'vitest';
import { ROLE_STYLE } from './roleStyles';

// A translucent background composited onto the white card is invisible when the
// text is the same colour as the card. The "You" tag used to be exactly that.
describe('role tag colours', () => {
  it('never uses a translucent white tag background', () => {
    for (const [role, style] of Object.entries(ROLE_STYLE)) {
      expect(style.tag, `role ${role}`).not.toMatch(/bg-white\/\d+/);
    }
  });

  it('gives the user tag a solid background with readable text', () => {
    expect(ROLE_STYLE.user.tag).toBe('bg-primary text-primary-foreground');
  });
});
