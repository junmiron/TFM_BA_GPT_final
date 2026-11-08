// Copies the committed sample deliverables into the demo's public folder so
// the built SPA is self-contained (artifacts + replay log served statically).
// Run automatically as `npm run prebuild` before build/dev.
import { copyFileSync, existsSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..'); // demo/
const source = resolve(root, '..', 'examples', 'sample_session');
const artifactDir = resolve(root, 'public', 'api', 'files', 'demo');

if (!existsSync(source)) {
  console.error(`prebuild: examples/sample_session/ not found. Run scripts/export_sample_session.py first.`);
  process.exit(1);
}
mkdirSync(artifactDir, { recursive: true });

const deliverables = [
  'functional_specification.pdf',
  'functional_specification.html',
  'functional_specification.md',
  'functional_specification.formatted.md',
  'interview.jsonl',
  'canvas_diagram.md',
  'process_diagram.mmd',
  'process_diagram.png',
  'process_diagram.svg',
  'process_diagram_2.mmd',
  'process_diagram_2.png',
  'process_diagram_2.svg',
  'process_diagram_3.mmd',
  'process_diagram_3.png',
  'process_diagram_3.svg',
  'process_diagram_4.mmd',
  'process_diagram_4.png',
  'process_diagram_4.svg',
];

let copied = 0;
for (const name of deliverables) {
  const from = resolve(source, name);
  if (existsSync(from)) {
    copyFileSync(from, resolve(artifactDir, name));
    copied += 1;
  }
}
copyFileSync(resolve(source, 'replay', 'events.jsonl'), resolve(root, 'public', 'events.jsonl'));
copyFileSync(resolve(source, 'replay', 'meta.json'), resolve(root, 'public', 'meta.json'));
console.log(`prebuild: copied ${copied} sample deliverables + replay log into demo/public/`);
