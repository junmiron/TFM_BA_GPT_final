import type { Artifact } from './types';

const PRIORITY = [
  'functional_specification.md',
  'functional_specification.pdf',
  'functional_specification.html',
];

function rank(artifact: Artifact): number {
  const index = PRIORITY.indexOf(artifact.name);
  if (index >= 0) return index;
  if (/process_diagram/i.test(artifact.name) && artifact.name.endsWith('.png')) return 10;
  return 20;
}

/** Specification and diagrams first, then anything else, both alphabetical. */
export function sortArtifacts(artifacts: Artifact[]): Artifact[] {
  return [...artifacts].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
}

/** The markdown spec that the header's Download Spec button fetches. */
export function findSpecArtifact(artifacts: Artifact[]): Artifact | undefined {
  return (
    artifacts.find((a) => a.name === 'functional_specification.md') ??
    artifacts.find((a) => a.name === 'functional_specification.pdf') ??
    artifacts.find((a) => a.name === 'functional_specification.html')
  );
}
