# Architecture — LLM Wiki

_Last updated: 2026-04-12_
_Derived from: PROJECT.md rev 2_

---

## Components

### 1. CLI Entry Points (`tools/`)

Four standalone scripts. Each is a top-level command; none import from each other.

| Script            | Responsibility                                              | State owned                          |
|-------------------|-------------------------------------------------------------|--------------------------------------|
| `ingest.py`       | Source extraction → LLM synthesis → batch review → commit   | Batch (in-memory until commit)       |
| `lint.py`         | Five health checks against wiki pages; optional `--save`    | None (read-only; writes lint-report) |
| `build_graph.py`  | Rebuild `graph.json` + `graph.html` from wiki pages         | `graph.json` SHA256 cache            |
| `query.py`        | Read-only question answering against wiki; `--save` deferred| None                                 |

### 2. Source Extraction Layer

Converts raw inputs into plain text for the LLM. Three extractors:

| Extractor     | Input           | Mechanism                                                     |
|---------------|-----------------|---------------------------------------------------------------|
| URL fetcher   | HTTP(S) URLs    | HTTP GET → HTML → text (readability / trafilatura / bs4)      |
| PDF extractor | `.pdf` files    | pdfplumber text extraction; Tesseract OCR fallback (AD-6)     |
| Text reader   | `.txt` / `.md`  | Direct file read                                              |

Contract: every extractor returns `(text: str, metadata: dict)`. Metadata includes source path, extraction method, and timestamp.

### 3. LLM Provider Abstraction

A thin provider interface wrapping two backends. The abstraction shields callers from provider differences.

| Provider   | Endpoint                               | Model                   | Chunk threshold |
|------------|----------------------------------------|-------------------------|-----------------|
| Gemini     | Google AI API                          | `gemini-3-flash-preview`| 750,000 tokens  |
| LM Studio  | `http://localhost:1234/v1` (OpenAI-compatible) | Qwen 3.5 9B       | 4,000 tokens    |

Responsibilities:
- Provider selection (config or runtime prompt).
- LM Studio health check with retry/switch prompt (AD-9).
- Chunking: split source text when it exceeds the provider's threshold (AD-5). Overlapping chunk boundaries.
- Chat completion call: send system prompt + user content, receive structured response.

### 4. Batch Proposal Engine

Receives extracted text + existing wiki state (via `index.md`), produces a set of proposed page operations.

Steps:
1. LLM reads `index.md` to identify related existing pages.
2. LLM reads relevant existing pages for context.
3. LLM proposes new/updated pages as a batch.
4. Contradiction detection: diff proposed content against existing pages, flag conflicts (AD-8).
5. Output: ordered list of `PageProposal(title, slug, content, conflicts[], action: create|update)`.

State: in-memory batch. Nothing written to disk until commit.

### 5. CLI Review Loop

Interactive terminal loop where the user reviews each `PageProposal` sequentially.

Per page:
- Display diff (new content or delta against existing page).
- Open in `$EDITOR` for edits (C-9).
- Accept → page moves to approved set.
- Reject → user provides reason → LLM re-proposes (AD-4, loops until accept or abandon).
- Conflict resolution: per-conflict choice of update-in-place or append-conflict-note (AD-8).

On edit: trigger scoped re-evaluation of downstream pages with wikilink dependency on the edited page (AD-3). Sequential, blocking.

### 6. Commit Layer

Atomic write of the approved batch to the vault.

Steps:
1. Write each approved page to `vault/wiki/{category}/{slug}.md`.
2. Regenerate `vault/wiki/index.md` (full catalog).
3. Append operation record to `vault/wiki/log.md`.
4. Auto-committed, no approval needed (AD-11).

Failure mode: if any write fails mid-batch, roll back all writes from this batch. The vault must not end up in a partial state (AD-2).

### 7. Lint Engine (`lint.py`)

Five on-demand health checks (details TBD in contract, expected checks):
- Orphan pages (no inbound wikilinks).
- Broken wikilinks (target page doesn't exist).
- Duplicate slugs.
- Empty pages.
- Index staleness (index.md out of sync with actual files).

Output: terminal report. `--save` writes `vault/wiki/lint-report.md`.

### 8. Graph Builder (`build_graph.py`)

Standalone tool, not called by ingest (AD-12).

Pipeline:
1. Scan all wiki pages. Compare SHA256 hashes against `graph.json` cache — skip unchanged pages.
2. Extract `EXTRACTED` edges from `[[wikilinks]]` in page content (C-6).
3. (Unless `--no-infer`) Send pages to LLM for `INFERRED` edge detection with confidence scores. Edges below threshold marked `AMBIGUOUS`.
4. Build NetworkX graph. Run Louvain community detection for topic clusters.
5. Serialize to `vault/graph/graph.json`.
6. Generate self-contained `vault/graph/graph.html` using vis.js from CDN (C-12, C-13).
7. `--open` flag opens the HTML file in the default browser.

### 9. Query Engine (`query.py`)

Read-only in MVP. Reads `index.md` → identifies relevant pages → sends question + page content to LLM → prints answer. `--save` prints "coming soon" (AD-13).

---

## Dependencies

### Python Packages (Runtime)

| Package           | Purpose                                       | Required by         |
|-------------------|-----------------------------------------------|---------------------|
| `google-genai`    | Gemini API client                             | LLM provider        |
| `openai`          | LM Studio OpenAI-compatible client            | LLM provider        |
| `pdfplumber`      | PDF text extraction                           | Source extraction    |
| `pytesseract`     | Tesseract OCR Python binding                  | Source extraction    |
| `requests`        | HTTP fetching for URL sources                 | Source extraction    |
| `beautifulsoup4`  | HTML → text conversion                        | Source extraction    |
| `networkx`        | Graph construction and traversal              | Graph builder        |
| `python-louvain`  | Community detection (Louvain algorithm)        | Graph builder        |
| `python-dotenv`   | Load `.env` for API keys                      | Config               |
| `tiktoken`        | Token counting for chunking decisions         | LLM provider        |

### System Dependencies

| Dependency   | Purpose                        | Install responsibility |
|--------------|--------------------------------|------------------------|
| Tesseract    | OCR engine for scanned PDFs    | User (C-11)            |
| `$EDITOR`    | User's preferred text editor   | User (C-9)             |
| Python 3.10+ | Runtime                       | User                   |

### External Services

| Service      | Usage                          | Failure impact                       |
|--------------|--------------------------------|--------------------------------------|
| Gemini API   | LLM calls (when selected)     | Ingest/query blocked; switch to LM Studio |
| LM Studio    | LLM calls (when selected)     | Retry prompt + Gemini escape hatch (AD-9)  |
| vis.js CDN   | Graph viewer (first load only) | graph.html won't render until online (L-10) |

---

## Integration Points

### I-1: Source → Extraction Layer
- **Boundary:** raw file/URL → structured `(text, metadata)` tuple.
- **Validation:** file existence check, URL reachability, PDF corruption detection, OCR quality gate (character count threshold per AD-6).
- **Failure:** extraction error → skip source with clear error message. Never pass empty text downstream.

### I-2: Extraction Layer → LLM Provider
- **Boundary:** extracted text → chunked (if needed) LLM prompts.
- **Validation:** token count against provider threshold before sending. Chunk overlap integrity.
- **Failure:** API error / timeout → retry with backoff (not in MVP per L-8). LM Studio unreachable → AD-9 retry loop.

### I-3: LLM Provider → Batch Engine
- **Boundary:** raw LLM response → parsed `PageProposal` objects.
- **Validation:** response must parse into expected schema (title, content, wikilinks). Malformed responses rejected and re-requested.
- **Failure:** unparseable response → retry with stricter prompt. After N failures → abort with log entry.

### I-4: Batch Engine → Review Loop
- **Boundary:** list of `PageProposal` objects → interactive terminal session.
- **Validation:** batch must be non-empty. Each proposal must have a valid slug and content.
- **Failure:** empty batch → "No pages proposed" message and clean exit.

### I-5: Review Loop → LLM (Edit Propagation)
- **Boundary:** user edit on page A → re-evaluation request for dependent pages.
- **Validation:** dependency scoping via wikilink analysis. Only pages with `[[Page A]]` references are re-evaluated.
- **Failure:** re-evaluation failure → keep original proposal, warn user.

### I-6: Review Loop → Commit Layer
- **Boundary:** approved batch → atomic disk writes.
- **Validation:** slug uniqueness (append hash on collision per AD-7). Write permissions on vault directory.
- **Failure:** disk write failure → full batch rollback. No partial commits.

### I-7: Wiki Pages → Graph Builder
- **Boundary:** markdown files on disk → NetworkX graph.
- **Validation:** SHA256 hash comparison for incremental processing. Wikilink regex extraction.
- **Failure:** malformed page → skip with warning. Graph build continues with available pages.

### I-8: Graph Builder → LLM (Inference)
- **Boundary:** page content → inferred edges with confidence scores.
- **Validation:** confidence threshold filtering. Edges below threshold marked `AMBIGUOUS`.
- **Failure:** inference failure for a page → structural edges only for that page. Build continues.

### I-9: Config → All Components
- **Boundary:** `config.json` + `.env` → runtime parameters.
- **Validation:** required fields check on startup. Missing vault path or provider → hard fail with actionable error.
- **Failure:** missing config → exit with usage instructions. Missing `.env` key → exit with specific key name.

---

## Top Risks

| ID   | Risk                                                        | Likelihood | Impact | Mitigation                                              |
|------|-------------------------------------------------------------|------------|--------|---------------------------------------------------------|
| R-1  | LLM produces unparseable or structurally wrong responses    | HIGH       | HIGH   | Strict output schema in prompts. Parse validation. Retry with stricter prompt on failure. |
| R-2  | Contradiction detection misses conflicts or flags false positives | MEDIUM | HIGH   | User is always in the loop (AD-8). False negatives are the real danger — conservative matching preferred. |
| R-3  | Chunk seam loss degrades synthesis quality (especially LM Studio at 4k) | HIGH | MEDIUM | Overlapping chunk boundaries. Cross-chunk summary pass. Accept as known limitation (L-2). |
| R-4  | Gemini free-tier rate limits block rapid successive ingests  | MEDIUM     | MEDIUM | No retry/backoff in MVP (L-8). User must pace manually. Document in README. |
| R-5  | index.md navigation breaks down beyond ~300 pages           | LOW (MVP)  | HIGH   | Soft warning at 300 pages (L-1). Design query.py to be extensible with search later. |
| R-6  | INFERRED graph edges are wrong, polluting the knowledge graph | MEDIUM   | MEDIUM | Confidence thresholds. AMBIGUOUS edge type. User must visually inspect graph.html (L-9). |
| R-7  | Partial commit corrupts vault state                         | LOW        | CRITICAL| Atomic batch-then-commit (AD-2). Full rollback on any write failure. |
| R-8  | Tesseract OCR produces garbage on low-quality scans         | MEDIUM     | LOW    | Character count quality gate. User notification when OCR triggers (AD-6). Accept as L-3. |
| R-9  | Edit propagation makes large batches extremely slow         | MEDIUM     | MEDIUM | Scope re-evaluation to wikilink-dependent pages only (AD-3). Accept sequential trade-off. |
| R-10 | LM Studio not running when selected, user frustration       | HIGH       | LOW    | Retry prompt with Gemini escape hatch (AD-9). Not a hard failure. |

---

## Bottlenecks

### B-1: Sequential Edit Propagation (AD-3)
**Where:** Review loop, when user edits an upstream page.
**Why:** Every edit triggers synchronous LLM re-evaluation of all downstream dependent pages. With a 15-page batch (A-10) where most pages interlink, a single edit can cascade into multiple LLM calls.
**Severity:** Medium. Acceptable for MVP batch sizes. Becomes painful if batches grow beyond ~20 pages.
**Mitigation:** Scope re-evaluation strictly to pages containing `[[edited page]]` wikilinks. Do not re-evaluate pages without direct dependency.

### B-2: LM Studio Context Window (4k Chunk Threshold)
**Where:** Source extraction → LLM provider for any non-trivial source.
**Why:** At 4,000 tokens, almost every real document gets chunked. Each chunk is a separate LLM call. A 20,000-token article becomes 5+ calls, each losing cross-chunk context.
**Severity:** High for LM Studio users. Gemini users are unaffected for documents under 750k tokens.
**Mitigation:** Overlapping chunk boundaries. Consider a merge/summary pass across chunk outputs. Document that Gemini is the recommended provider for large sources.

### B-3: Graph Inference LLM Calls
**Where:** `build_graph.py` without `--no-infer`.
**Why:** Every wiki page is sent to the LLM to detect implicit relationships. At 300 pages, this is 300+ LLM calls. With Gemini rate limits or LM Studio latency, this is slow.
**Severity:** High. This is why graph building is a separate command (AD-12) with `--no-infer` as an escape hatch.
**Mitigation:** SHA256 cache ensures only changed pages are reprocessed on incremental rebuilds. `--no-infer` flag for fast structural-only builds.

### B-4: Batch Size Scaling
**Where:** Batch proposal engine + review loop.
**Why:** A single dense source (e.g., a textbook chapter) could propose 15+ pages. The review loop is sequential — the user must review each one. Combined with edit propagation (B-1), total wall-clock time scales roughly as O(pages * edits).
**Severity:** Medium. Bounded by assumption A-10 (max ~15 pages per ingest).
**Mitigation:** If real usage exceeds A-10, consider batch splitting or parallel-safe review for independent page subsets.

### B-5: index.md as Navigation Ceiling
**Where:** Every LLM call that needs wiki context (ingest, query).
**Why:** The entire `index.md` is sent to the LLM as context. At 300 pages with titles and summaries, `index.md` itself becomes a large token payload, reducing available context for actual page content.
**Severity:** Low in MVP. Becomes the dominant bottleneck at scale.
**Mitigation:** Accepted as L-1. When 300-page warning triggers, the system needs search infrastructure (embeddings, filtering) to replace full-index reads.

---

## Component Dependency Map

```
config.json + .env
       │
       ▼
 ┌─────────────┐
 │  CLI Entry   │  (ingest / lint / build_graph / query)
 └──────┬───────┘
        │
  ┌─────┴──────────────────┐
  │                        │
  ▼                        ▼
┌──────────────┐    ┌──────────────┐
│   Source      │    │  LLM Provider │
│  Extraction   │    │  Abstraction  │
└──────┬───────┘    └──────┬───────┘
       │                   │
       └─────────┬─────────┘
                 ▼
        ┌────────────────┐
        │  Batch Proposal │
        │     Engine      │
        └───────┬────────┘
                │
                ▼
        ┌────────────────┐
        │  CLI Review     │◄──── LLM (edit propagation)
        │     Loop        │
        └───────┬────────┘
                │
                ▼
        ┌────────────────┐
        │  Commit Layer   │───► vault/wiki/ (pages, index.md, log.md)
        └────────────────┘

Standalone:
  lint.py ───► vault/wiki/ (read) ───► terminal / lint-report.md
  build_graph.py ───► vault/wiki/ (read) ───► vault/graph/ (write)
  query.py ───► vault/wiki/ (read via index.md) ───► terminal
```
