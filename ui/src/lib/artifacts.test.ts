import { describe, expect, it } from 'vitest';
import { findHtmlArtifact, findPdfArtifact } from './artifacts';
import type { Artifact } from './types';

const artifacts: Artifact[] = [
  { name: 'functional_specification.md', kind: 'markdown', size: 10, url: '/api/files/s1/functional_specification.md' },
  { name: 'functional_specification.pdf', kind: 'pdf', size: 20, url: '/api/files/s1/functional_specification.pdf' },
  { name: 'functional_specification.html', kind: 'html', size: 30, url: '/api/files/s1/functional_specification.html' },
  { name: 'process_diagram.png', kind: 'image', size: 40, url: '/api/files/s1/process_diagram.png' },
];

describe('spec artifact pickers', () => {
  it('the header button targets the PDF, not the markdown', () => {
    expect(findPdfArtifact(artifacts)?.name).toBe('functional_specification.pdf');
  });

  it('the web link targets the HTML file', () => {
    expect(findHtmlArtifact(artifacts)?.name).toBe('functional_specification.html');
  });

  it('missing deliverables yield undefined so the buttons grey out', () => {
    expect(findPdfArtifact([])).toBeUndefined();
    expect(findHtmlArtifact([{ name: 'spec.md', kind: 'markdown', size: 1, url: '/x' }])).toBeUndefined();
  });
});
