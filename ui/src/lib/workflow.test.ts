import { describe, expect, it } from 'vitest';
import { deriveStageStates, stageIndexForSource } from './workflow';
import { findHtmlArtifact, findPdfArtifact, sortArtifacts } from './artifacts';

describe('workflow stage derivation', () => {
  it('maps agent sources to stages', () => {
    expect(stageIndexForSource('interviewer_agent')).toBe(0);
    expect(stageIndexForSource('functional_spec_writer_agent')).toBe(2);
    expect(stageIndexForSource('planning_agent')).toBe(-1);
    expect(stageIndexForSource('UNKNOWN')).toBe(-1);
  });

  it('marks earlier stages done and the current one active', () => {
    const states = deriveStageStates(['planning_agent', 'interviewer_agent', 'functional_spec_writer_agent'], false);
    expect(states.interview).toBe('done');
    expect(states.summary).toBe('done');
    expect(states.spec).toBe('active');
    expect(states.review).toBe('pending');
  });

  it('a finished run closes every stage', () => {
    const states = deriveStageStates([], true);
    expect(Object.values(states).every((s) => s === 'done')).toBe(true);
  });
});

describe('artifact ordering', () => {
  const mk = (name: string): { name: string; kind: string; size: number; url: string } => ({
    name,
    kind: name.split('.').pop() ?? '',
    size: 10,
    url: `/api/files/s/${name}`,
  });

  it('puts the specification first, then diagrams', () => {
    const order = sortArtifacts([mk('notes.txt'), mk('process_diagram_2.png'), mk('functional_specification.pdf'), mk('functional_specification.md')]).map((a) => a.name);
    expect(order).toEqual([
      'functional_specification.md',
      'functional_specification.pdf',
      'process_diagram_2.png',
      'notes.txt',
    ]);
  });

  it('the header download targets the PDF deliverable', () => {
    expect(findPdfArtifact([mk('functional_specification.html'), mk('functional_specification.pdf')])?.name)
      .toBe('functional_specification.pdf');
    expect(findPdfArtifact([mk('functional_specification.md')])).toBeUndefined();
    expect(findPdfArtifact([])).toBeUndefined();
    expect(findHtmlArtifact([mk('functional_specification.html')])?.name).toBe('functional_specification.html');
  });
});
