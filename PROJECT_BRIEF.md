# PROJECT_BRIEF.md — LLM Wiki

_Last updated: 2026-04-12 (rev 2 — graph stack added, chunking thresholds updated)_

## What We're Building

A CLI tool that maintains a personal, persistent knowledge base (wiki) inside a dedicated
Obsidian vault. The user feeds it raw sources (URLs, PDFs, plain text). The tool processes
each source with an LLM, proposes wiki pages to create or update, and lets the user review,
edit, and approve them before anything is written to disk. The wiki is a structured set of
interlinked markdown files — summaries, entity pages, concept pages, a master index, a
change log — that grows richer with every source ingested. After each ingest, a standalone
graph tool rebuilds an interactive `graph/graph.html` from all wikilinks and LLM-inferred
relationships.

The LLM writes and maintains all wiki content. The user curates sources, approves changes,
and directs emphasis. Nothing is written without user approval (except mechanical bookkeeping
files).

---

## Success Criteria

1. User can ingest a URL, PDF, or plain text file with a single CLI command.
2. User can choose the LLM provider (Gemini or LM Studio) before each ingestion.
3. All proposed wiki pages surface as a reviewable batch before anything is written.
4. User can approve, edit (in system editor), or reject each page individually.
5. Rejected pages are re-proposed after user provides a rejection reason.
6. When a page is edited, the LLM re-evaluates downstream pages in the same batch before
   showing them to the user.
7. Contradictions between a new source and existing wiki content are flagged explicitly —
   never silently overwritten.
8. `index.md` and `log.md` are updated automatically after every ingest (no approval loop).
9. The wiki directory is a valid Obsidian vault with working internal links.
10. LM Studio chunks any source exceeding 4,000 tokens. Gemini chunks only above 750,000
    tokens. Both thresholds are configurable.
11. Running `python tools/build_graph.py` produces `graph/graph.html` — a self-contained
    interactive visualization of the wiki's knowledge graph.
12. Graph edges are typed: EXTRACTED (explicit wikilinks), INFERRED (LLM-detected implicit
    relationships with confidence score), AMBIGUOUS (low-confidence inferred).
13. Graph rebuild uses SHA256 caching — only pages changed since the last build are
    reprocessed.

---

## Anti-Goals (Explicitly NOT Building)

- **No RAG / vector search.** The index file is the navigation mechanism. No embeddings,
  no vector DB, no semantic retrieval infrastructure.
- **No web UI on day one.** CLI only. Web UI is a future phase.
- **No query-to-wiki filing on day one.** The `--save` flag pattern is pre-decided
  (query answer saved as a first-class wiki page at a user-specified path) but implemented
  in a future phase.
- **No multi-user / team features.** Single user, local machine only.
- **No generic LLM provider abstraction.** Only Gemini (via Google AI Studio) and LM Studio
  (OpenAI-compatible local API). No plugin system, no provider registry.
- **No batch / unattended ingestion.** Every ingest session requires the user present for
  the approval loop.
- **No Obsidian plugin.** The tool writes files to disk; Obsidian just reads them.
- **No automated lint / wiki health-check on a schedule.** Lint is a manual on-demand
  operation.
- **No graph server.** `graph.html` is self-contained — opens in any browser, no server
  required.

---

## Constraints

### Technical
- **Language:** Python. No other language for core tool. vis.js loaded from CDN in
  `graph.html` (no Node.js required).
- **LLM Providers:**
  - Gemini via Google AI Studio free API (`gemini-3-flash-preview`, 1M token context).
  - LM Studio via local OpenAI-compatible endpoint (`http://localhost:1234/v1`), model:
    Qwen 3.5 9B (or whatever is loaded).
- **Chunking:**
  - LM Studio: chunk any source exceeding **4,000 tokens**.
  - Gemini: chunk only when source exceeds **750,000 tokens**.
  - Both thresholds configurable. Chunk boundaries overlap to preserve context.
- **Graph stack:** NetworkX (graph construction), python-louvain (community detection),
  vis.js via CDN (visualization). Output: `graph/graph.json` (cached data) +
  `graph/graph.html` (self-contained viewer).
- **Wiki format:** Markdown files only. Obsidian-compatible internal links (`[[Page Name]]`).
- **Vault structure:** Dedicated vault, not mixed with existing notes.
- **Raw sources:** Stored in a separate directory outside the Obsidian vault. Immutable —
  the tool reads but never modifies them.
- **System editor:** Approval/edit loop opens `$EDITOR` (or falls back to `nano`).
- **Reference implementation:** SamurAIGPT/llm-wiki-agent `tools/` directory used as
  reference for ingest, lint, query, and graph tool design. Not copied verbatim — adapted
  to fit this project's approval loop and provider abstraction.

### Security
- API keys stored in environment variables or a local `.env` file. Never hardcoded.
- LM Studio runs locally; no external calls for private-mode ingestion.
- Raw sources never leave the machine when LM Studio is the selected provider.

### Performance
- No hard latency targets for MVP. LLM calls are the bottleneck and accepted as slow.
- Chunking must not silently lose content. Chunk boundaries must overlap.
- Graph rebuild: SHA256 cache on each wiki page. Only reprocess pages whose content has
  changed since the last `build_graph.py` run.

---

## Scope

### IN (MVP)
- `python tools/ingest.py <source>` — ingest a URL, PDF, or text file.
- `python tools/lint.py [--save]` — on-demand wiki health check.
- `python tools/build_graph.py [--no-infer] [--open]` — rebuild knowledge graph.
- `python tools/query.py "<question>" [--save [path]]` — query wiki (read-only in MVP;
  `--save` deferred to future phase but interface pre-decided).
- Provider selection prompt at start of each ingest session.
- Source content extraction: URL → fetch + markdown, PDF → text extraction + OCR fallback,
  plain text → read directly.
- Chunking: LM Studio above 4k tokens, Gemini above 750k tokens.
- LLM processing: source summary page + affected entity/concept pages + proposed updates.
- Batch review: all proposed pages shown as a batch, one at a time, with diff vs. current.
- Per-page actions: approve / edit in `$EDITOR` / reject with reason.
- Rejection loop: re-propose with user's reason incorporated.
- Edit propagation: upstream edit triggers LLM re-evaluation of remaining batch pages.
- Contradiction detection: flagged during review; user chooses update-in-place or
  append-conflict-note per conflict.
- Atomic commit: all approved pages written to disk in one pass.
- `index.md` auto-update + `log.md` auto-append on every ingest.
- Graph: `graph/graph.json` (node/edge cache, SHA256-keyed) + `graph/graph.html`
  (vis.js viewer). Edge types: EXTRACTED, INFERRED (with confidence), AMBIGUOUS.
  Louvain community detection for node clustering.
- Lint checks: orphan pages, broken wikilinks, missing entity pages (mentioned 3+ times,
  no dedicated page), contradictions, data gaps, suggested new sources.
- Config file: vault path, sources path, default provider, chunk thresholds, LM Studio
  endpoint.

### OUT (Future Phases)
- Web UI
- Query `--save` implementation (interface pre-decided, not built)
- Additional LLM providers
- Embedding-based search (e.g. qmd integration)
- Multi-vault support
- Image ingestion and inline image handling
- Marp / slide deck output
- Dataview frontmatter generation
- Automated scheduled lint
- Collaborative / multi-user mode

---

## Done-When Conditions

1. `python tools/ingest.py sources/article.pdf` runs end-to-end without error.
2. User is prompted to choose Gemini or LM Studio before processing begins.
3. LM Studio chunks above 4k tokens; Gemini chunks above 750k tokens.
4. After processing, a batch of proposed pages is displayed in the CLI.
5. User can cycle through pages, open each in `$EDITOR`, save, and hand the edit back.
6. Edited page triggers re-evaluation of remaining batch pages before they are shown.
7. Rejected page is re-proposed with the LLM incorporating the user's stated reason.
8. After full batch approval, all pages exist on disk in the Obsidian vault.
9. A contradiction is surfaced explicitly during review — not silently merged.
10. `index.md` is updated and `log.md` has a new timestamped entry without user prompting.
11. `python tools/build_graph.py` produces a valid `graph/graph.html` that opens in a
    browser and shows nodes (wiki pages) connected by typed edges.
12. Running the graph tool a second time without changes completes faster (SHA256 cache hit).
13. `python tools/lint.py` produces a list of health issues without modifying any files.
14. `python tools/lint.py --save` writes the report to `wiki/lint-report.md`.
15. Config file controls vault path, sources path, provider default, both chunk thresholds,
    and LM Studio endpoint.

---

## Unresolved

_All previously unresolved items are resolved. No items block progress._

| ID   | Item                          | Resolution                                                         |
|------|-------------------------------|--------------------------------------------------------------------|
| UR-1 | Gemini model                  | `gemini-3-flash-preview`. Free tier confirmed. 1M token context.   |
| UR-2 | Scanned PDF handling          | OCR via Tesseract. Auto-detected; user notified when triggered.    |
| UR-3 | LM Studio not running         | Retry prompt. Offer switch-to-Gemini escape hatch.                 |
| UR-4 | Wiki scale ceiling            | Soft warning at 300 pages. Accepted as known limitation.           |
| UR-5 | Contradiction resolution UX   | Per-conflict: update in place OR append conflict note.             |
| UR-6 | Page naming convention        | LLM-generated title → deterministic kebab-case slug.               |
| UR-7 | Graph implementation          | NetworkX + Louvain + vis.js. graph.html, SHA256 cache, 3 edge      |
|      |                               | types. Reference: SamurAIGPT/llm-wiki-agent build_graph.py.       |
| UR-8 | Query --save design           | Pre-decided: save answer as wiki page at user-specified path.      |
|      |                               | Implementation deferred to future phase.                           |