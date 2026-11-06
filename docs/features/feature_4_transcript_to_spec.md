# Feature 4 — Load a meeting transcript and generate the spec from it

Status: implemented (2026-11-06).

Implemented as:
- `lib/transcript_loader.py`: extracts text from `.txt`, `.md`, `.docx`,
  `.pdf` (existing PyMuPDF/zipfile readers), `.vtt`, `.srt` (timings stripped).
- The session composer in the left rail accepts a transcript file (max 2 MB);
  `POST /api/sessions` receives `transcript_base64` + `transcript_name`, saves
  `source_transcript.txt` in the session folder before the run starts.
- `_start_run` seeds the task text with the transcript and the instruction to
  interview only for gaps; the checker still cross-validates the spec.
- Tests: `tests/test_continuation_transcript.py`.

## Goal
The user can upload a transcript of a real meeting (interview, discovery call)
and the system turns it into the functional specification, using the transcript as
the primary source instead of (or before) the simulated interview.

## Current state
- The only input today is the `task` text in the session rail (`POST /api/sessions`
  with `{"task": "..."}`); everything else comes from the live interview.
- `lib/rag_helpers.py` already has text extractors for PDF (`_read_pdf` via pymupdf)
  and DOCX (`_read_docx` via stdlib zipfile/OOXML), and a robust
  `split_text(text, 500, 50)` chunker.
- `interview.jsonl` is written by tools in `lib/agents_tools_helpers.py`; the
  coverage/routing helpers (`question_from_coverage`, `current_round`) operate on
  Q&A pairs, so transcript-derived Q&A can plug straight in.
- No upload endpoint exists; CORS allows only GET/POST (fine for a JSON/text
  upload from the UI).

## Design

### Input formats
- Plain text / Markdown: verbatim.
- DOCX: extracted with the existing `_read_docx`.
- PDF: extracted with the existing `_read_pdf`.
- VTT/SRT (from Zoom/Teams auto-captions): strip timestamps, merge speaker lines.
- JSONL (exported meeting notes): each line's `text`/`message` field.
Size cap: `TRANSCRIPT_MAX_CHARS` (default 200000); beyond that the backend keeps
the head and tail with a warning event in the transcript.

### Flow
1. UI: in the session rail, next to the task box, an "Upload transcript" file
   picker (accepts .txt/.md/.docx/.pdf/.vtt/.srt/.jsonl). Optionally paste text
   directly into the task box prefixed with `TRANSCRIPT:` for power users.
2. `POST /api/sessions` accepts an optional `transcript` field (text) or a
   multipart upload; the backend:
   - extracts text (helper `lib/rag_helpers.extract_transcript_text(path)`) —
     reuse existing PDF/DOCX readers;
   - saves it as `<session_dir>/source_transcript.txt` (an artifact in its own
     right, visible in the artifacts panel);
   - speaker diarization: if lines look like `Name: text`, split into speaker turns
     (regex `^[A-Z][A-Za-z .-]{0,30}:\s`), else treat as one blob.
3. New pipeline mode "transcript-driven" (`create_workflow(..., transcript=...)`):
   - an extraction agent (added to the team, model lane = tools lane) reads the
     transcript in chunks and emits candidate requirements, decisions, open
     questions, and glossary terms as structured JSON — written to
     `<session_dir>/transcript_facts.json`;
   - those facts seed `interview.jsonl` as pre-answered coverage items: each
     extracted requirement gets a "source: transcript" entry;
   - the interviewer only asks about GAPS: coverage table already lists what the
     transcript answered, so `question_from_coverage` naturally targets what is
     missing. If the transcript is rich, the interview is short; if thin, the
     normal interview proceeds.
   - writer/checker/diagram/deliverable stages unchanged.
4. Chainlit (`app2.py`): an upload attachment prompt (Chainlit supports file
   uploads) mapping to the same session flow.

### Prompting the extraction agent
Give it a fixed schema:

```json
{
  "requirements": [{"text": "...", "confidence": "high|medium|low", "speaker": "..."}],
  "decisions":    [{"decision": "...", "rationale": "..."}],
  "open_questions":[{"question": "..."}],
  "glossary":     [{"term": "...", "definition": "..."}],
  "process_steps":[{"step": "...", "from": "...", "to": "..."}]
}
```

The `process_steps` feed the Mermaid diagram creator directly (already the shape
the diagram agent uses). Low-confidence items become interview questions instead
of spec facts — never silently invented.

### Guardrails
- No hallucination rule: the writer may only use facts from `transcript_facts.json`
  or real interview answers; the checker round already cross-checks spec against
  source material, extend it to check against the transcript file.
- Long transcripts: extraction runs chunk-by-chunk with a merge pass; MAX_MESSAGES
  guard still applies.

## Changes
- `server/api.py`: transcript field/multipart in `POST /api/sessions`; helper
  `extract_transcript_text` in `lib/rag_helpers.py`; save file into session dir.
- `lib/pipeline.py`: `create_workflow(..., transcript_text: Optional[str])` +
  `transcript_extractor_agent` with JSON schema output; seed interview coverage.
- `lib/agents_tools_helpers.py`: `seed_interview_from_facts(session_dir, facts)`
  writing pre-answered items into `interview.jsonl`.
- `ui/src/components/SessionRail.tsx`: file input + "or paste transcript" toggle.
- `.env`: `TRANSCRIPT_MAX_CHARS=200000`.
- Tests: extractor handles txt/docx/pdf/vtt; diarization; facts→coverage seeding;
  writer prompt contains transcript-derived requirements; end-to-end smoke with a
  canned 1-page transcript fixture (keep the fixture in `tests/fixtures/`).

## Acceptance criteria
1. Uploading a meeting transcript produces a spec whose requirements trace to
   transcript lines (checker verifies).
2. The interview only asks about what the transcript did not cover.
3. Unsupported/low-confidence items surface as questions, not as spec facts.
4. `source_transcript.txt` appears as a downloadable artifact.

## Open questions
- Should transcript sessions still run the simulated stakeholder for gap-filling,
  or ask the real user (UI) the gap questions? (Recommend: real user when
  SIMULATE_HUMAN=false, simulator otherwise — same routing as today.)
- Do we want the transcript stored in the RAG immediately, or only after the
  Feature 1 satisfaction gate? (Recommend: only after satisfaction, consistent
  with Feature 1.)
