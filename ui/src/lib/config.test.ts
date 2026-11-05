import { describe, it, expect } from 'vitest';
import { resolveApiBaseUrl } from './config';

describe('resolveApiBaseUrl', () => {
  it('falls back to the local default when nothing is configured', () => {
    expect(resolveApiBaseUrl()).toBe('http://127.0.0.1:8000');
  });
});
