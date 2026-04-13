# PROJECT.md — LLM Wiki

_Last updated: 2026-04-12 (rev 13 — S-10 Query Tool completed)_
_Status: S-7 in progress ([~]), S-10 done ([x])._

---

## System Overview

A local Python CLI tool that builds and maintains a persistent, interlinked markdown wiki
inside a dedicated Obsidian vault. The user feeds raw sources (URLs, PDFs, plain text).
The tool extracts content, sends it to an LLM, and receives proposed wiki pages. The user
reviews the batch, edits pages in their system editor, and approves before anything is
written to disk. The LLM re-evaluates downstream pages in the batch whenever the user edits
an upstream one. Contradictions with existing wiki content are flagged and resolved
per-conflict by the user. Bookkeeping files (index.md, log.md) are auto-committed. A
standalone graph tool rebuilds an interactive `graph/graph.html` after each ingest. A lint
command performs on-demand wiki health checks.

**Entry points:**
- `python tools/ingest.py <source>` — ingest a URL, PDF, or text file
- `python tools/lint.py [--save]` — on-demand wiki health check
- `python tools/build_graph.py [--no-infer] [--open]` — rebuild knowledge graph
- `python tools/query.py "<question>"` — query wiki (read-only in MVP)

**Providers:** Gemini 3 Flash Preview (`gemini-3-flash-preview`, 1M token context, free
tier) and LM Studio (local OpenAI-compatible endpoint, Qwen 3.5 9B).

**Reference implementation:** SamurAIGPT/llm-wiki-agent `tools/` directory. Adapted, not
copied. Key borrowings: ingest page-touch checklist, lint health checks, graph stack
(NetworkX + Louvain + vis.js), SHA256 cache pattern, query `--save` interface design.

---

## Directory Structure

```
project-root/
├── tools/
│   ├── ingest.py          ← source ingestion + approval loop
│   ├── lint.py            ← wiki health checks
│   ├── build_graph.py     ← knowledge graph builder
│   └── query.py           ← wiki query (read-only MVP)
├── config.json            ← vault path, sources path, provider, thresholds
├── .env                   ← API keys (never committed)
│
sources/                   ← raw sources (OUTSIDE vault, immutable)
│   ├── articles/
│   ├── pdfs/
│   └── notes/
│
vault/                     ← Obsidian vault (wiki lives here)
    ├── wiki/
    │   ├── index.md       ← content catalog (auto-maintained)
    │   ├── log.md         ← append-only operation log (auto-maintained)
    │   ├── overview.md    ← evolving synthesis (LLM-maintained)
    │   ├── sources/       ← one summary page per ingested source
    │   ├── entities/      ← named entity pages
    │   ├── concepts/      ← concept/topic pages
    │   └── lint-report.md ← written by lint --save
    └── graph/
        ├── graph.json     ← node/edge cache (SHA256-keyed)
        └── graph.html     ← self-contained vis.js viewer
```

---

## Architecture Decisions

### AD-1: No RAG — index.md as navigation
The index file is the LLM's map of the wiki. On each ingest or query, the LLM reads
index.md first to identify relevant pages, then drills into them. No embeddings, no vector
DB. Rationale: eliminates infrastructure complexity for MVP; works reliably up to ~300
pages. Soft warning emitted at 300 pages to signal when search tooling should be added.

### AD-2: Batch-then-commit, not write-as-you-go
All proposed pages are collected into a batch and shown to the user for review. Nothing
is written to disk until the full batch is approved. Rationale: prevents partial state
where some pages reflect the new source and others don't; makes the approval loop atomic.

### AD-3: Edit propagation is sequential, not parallel
When the user edits page A, the LLM re-evaluates all remaining unreviewed pages in the
batch before showing the next one. Synchronous and blocking. Rationale: parallel
re-evaluation would require the LLM to speculatively update pages the user hasn't seen,
creating confusion. Sequential is slower but predictable. Scope re-evaluation to pages
with a wikilink dependency on the edited page to reduce unnecessary LLM calls.

### AD-4: Rejection is a loop, not a skip
A rejected page is re-proposed with the user's reason incorporated. The loop continues
until the user approves or explicitly abandons the page. Rationale: a page the LLM thinks
should exist probably should; the user's rejection reason is signal, not a veto.

### AD-5: Chunking strategy is provider-specific with explicit thresholds
- **LM Studio:** chunk any source exceeding **4,000 tokens**. The local Qwen model has a
  limited, unreliable context window. Chunking is essentially always-on for any non-trivial
  source.
- **Gemini:** chunk only when source exceeds **750,000 tokens**. The 1M token context
  handles all but the largest documents in one shot. Forcing chunking on small sources
  wastes API calls and degrades synthesis coherence.
- Both thresholds are configurable in `config.json`.
- Chunk boundaries overlap to avoid losing context at seams.

### AD-6: OCR via Tesseract, gated behind detection
PDF ingestion first attempts text extraction (pdfplumber or pymupdf). If extracted text
is below a minimum character threshold (indicating a scanned/image-only PDF), Tesseract
OCR is invoked automatically. The user is notified that OCR is running. Rationale: most
PDFs are text-native; OCR is a fallback, not the default path.

### AD-7: Page filenames are deterministic slugs of LLM-generated titles
The LLM proposes a human-readable title (e.g. "Attention Is All You Need"). The system
derives the filename as a kebab-case slug (e.g. `attention-is-all-you-need.md`).
Collisions are resolved by appending a short hash. Rationale: consistent, git-friendly,
predictable across sessions; removes a manual confirmation step from the review loop.

### AD-8: Contradiction resolution is per-conflict, user-directed
When a new source conflicts with an existing wiki page, the LLM flags the conflict and
presents two options during batch review:
- **Update in place** — LLM rewrites the affected section of the old page.
- **Append conflict note** — LLM appends a `⚠️ Conflicting claim (source, date)` block,
  leaving original intact.
The user picks per-conflict. Both options go through the standard approval loop.

### AD-9: LM Studio failure is a retry prompt, not a hard exit
At provider selection, if LM Studio is chosen, the tool pings `http://localhost:1234/v1/models`.
On failure: "LM Studio is not reachable. Start it and press Enter to retry, or type
'switch' to use Gemini instead." Rationale: LM Studio startup is manual and slow; hard-
failing forces the user to re-run the entire command.

### AD-10: Raw sources are immutable and stored outside the vault
Raw sources live in `sources/` outside the Obsidian vault. The tool reads; never writes.
Rationale: clean separation between source-of-truth and derived artifact.

### AD-11: index.md and log.md are auto-committed, no approval loop
Mechanical bookkeeping files. Neither contains synthesized knowledge. Requiring approval
adds friction with no benefit.

### AD-12: Graph is a standalone tool, not baked into ingest
`build_graph.py` is a separate command, not called automatically by ingest. The user
runs it when they want a fresh graph. Rationale: graph inference (LLM-detected implicit
relationships) is slow and expensive; the user should control when it runs. The `--no-infer`
flag skips semantic inference entirely for a fast structural-only rebuild.

Graph stack:
- **NetworkX** — graph construction and traversal
- **python-louvain** — community detection for node clustering by topic
- **vis.js** (CDN) — interactive browser visualization, no server required
- **SHA256 cache** — `graph.json` stores a hash per wiki page; only pages whose content
  changed since the last build are reprocessed. Makes incremental rebuilds fast.

Edge types:
- `EXTRACTED` — explicit `[[wikilink]]` found in page content
- `INFERRED` — LLM-detected implicit relationship (stored with confidence score 0–1)
- `AMBIGUOUS` — low-confidence inferred relationship (below configurable threshold)

Output: `vault/graph/graph.json` (cached data) + `vault/graph/graph.html`
(self-contained viewer that reads from graph.json).

### AD-13: Query --save interface pre-decided, implementation deferred
`query.py` accepts `--save` and `--save <path>` flags. When implemented, the answer is
saved as a first-class wiki page at the specified path (or user is prompted). This design
decision is locked now so the query interface doesn't need to change when the feature ships.
In MVP, `--save` prints a "coming soon" notice and exits cleanly.

---

## Active Constraints

| ID   | Constraint                                                                       |
|------|----------------------------------------------------------------------------------|
| C-1  | Python only. No other language for core tool.                                    |
| C-2  | Providers: Gemini 3 Flash Preview and LM Studio only. No others in MVP.          |
| C-3  | LM Studio endpoint: `http://localhost:1234/v1`. Configurable in config.json.     |
| C-4  | Gemini model: `gemini-3-flash-preview`. Free tier confirmed. 1M token context.   |
| C-5  | Wiki files: markdown only. No HTML, no non-text formats in wiki layer.           |
| C-6  | Obsidian wikilinks syntax (`[[Page Name]]`) required for graph EXTRACTED edges.  |
| C-7  | API keys in `.env` or environment variables. Never in source or config.          |
| C-8  | Sources directory is outside the Obsidian vault directory.                       |
| C-9  | System editor via `$EDITOR` env var; fallback to `nano`.                         |
| C-10 | LM Studio chunk threshold: 4,000 tokens. Gemini chunk threshold: 750,000 tokens. |
|      | Both configurable in config.json.                                                |
| C-11 | Tesseract must be installed separately. Tool warns clearly if missing.           |
| C-12 | vis.js loaded from CDN in graph.html. No npm, no build step.                     |
| C-13 | graph.html must be self-contained — readable offline after initial CDN load.     |

---

## Assumption Log

| ID   | Assumption                                                                       | Status    |
|------|----------------------------------------------------------------------------------|-----------|
| A-1  | `gemini-3-flash-preview` confirmed on free tier. 1M token context.               | CONFIRMED |
| A-2  | LM Studio exposes a fully OpenAI-compatible `/v1/chat/completions` endpoint.     | CONFIRMED |
| A-3  | Qwen 3.5 9B handles chunked ingestion (4k chunks) without critical coherence     | UNTESTED  |
|      | loss across chunks.                                                              |           |
| A-4  | index.md-based navigation is sufficient up to ~300 wiki pages.                   | ACCEPTED  |
| A-5  | pdfplumber text extraction is sufficient for text-native PDFs.                   | ASSUMED   |
| A-6  | Tesseract produces usable output for typical document scans (not handwriting).   | ASSUMED   |
| A-7  | The user's `$EDITOR` is set and functional on their machine.                     | ASSUMED   |
| A-8  | Obsidian reads the vault directory in real time; no sync step needed.            | CONFIRMED |
| A-9  | Kebab-case slugs from LLM titles are unique enough that hash collisions are      | ASSUMED   |
|      | rare in practice.                                                                |           |
| A-10 | A single ingest session touches at most ~15 wiki pages.                          | ASSUMED   |
| A-11 | NetworkX + python-louvain produce meaningful clusters at wiki sizes <300 pages.  | ASSUMED   |
| A-12 | LLM-inferred implicit relationships (INFERRED edges) have acceptable precision   | UNTESTED  |
|      | for Gemini 3 Flash; may be noisy for Qwen 3.5 9B.                               |           |

---

## Broken Assumptions

| ID  | Assumption broken | What actually happened | Impact | Resolution |
|-----|-------------------|------------------------|--------|------------|
| BA-1 | S-5 assumption: S-4 always hands off structurally valid update proposals. | S-4 Phase 1 parsing currently allows `action="update"` without `existing_page`, but S-5 requires non-empty `existing_path`. | Review handoff can fail despite successful batch generation. | Track as cross-slice contract gap; enforce `existing_page` for updates in S-4 parser. |

---

## Known Limitations

| ID  | Limitation                                                                           |
|-----|--------------------------------------------------------------------------------------|
| L-1 | index.md navigation degrades beyond ~300 pages. No search infrastructure in MVP.    |
| L-2 | LM Studio 4k chunk size means dense technical documents are split aggressively.     |
|     | Cross-chunk synthesis quality depends entirely on overlap and prompt design.         |
| L-3 | OCR quality depends on scan quality. Handwritten or low-DPI scans produce garbage   |
|     | with no warning beyond what Tesseract signals.                                       |
| L-4 | No image understanding. Images in PDFs or web pages are ignored entirely.            |
| L-5 | No query --save in MVP. Wiki is read-only outside ingest and lint sessions.          |
| L-6 | No version history beyond git if the user chooses to init a repo.                   |
| L-7 | Sequential edit propagation is slow on large batches with many upstream edits.      |
| L-8 | Gemini free tier has rate limits. Rapid successive ingests may hit quota. No        |
|     | retry/backoff logic in MVP.                                                          |
| L-9 | INFERRED graph edges are LLM-generated and may be wrong. No validation mechanism.  |
|     | User must inspect graph.html to catch false relationships.                           |
| L-10| graph.html requires internet access on first open to load vis.js from CDN.          |

---

## Slice History

| Slice | Status      | Description                                                          |
|-------|-------------|----------------------------------------------------------------------|
| S-0   | DONE        | PROJECT_BRIEF.md — requirements interview complete                   |
| S-0.5 | DONE        | Unresolved items resolved, PROJECT.md generated                      |
| S-0.6 | DONE        | Rev 2 — graph stack defined, chunking thresholds updated             |
| S-1   | DONE        | Foundation — config.json, vault/source dir init, provider abstraction|
| S-2   | DONE        | Source extraction — URL fetch, PDF (text + OCR fallback), plain text |
| S-3   | DONE        | LLM layer — Gemini + LM Studio clients, chunking, prompt design      |
| S-4   | DONE        | Batch proposal engine — page diffing, contradiction detection         |
| S-5   | DONE        | CLI review loop — validation, editor loop, reject/re-propose, conflict decisions |
| S-6   | NOT STARTED | Edit propagation — scoped re-evaluation on upstream edit             |
| S-7   | IN PROGRESS ([~]) | Commit layer — atomic write to vault, index.md + log.md update |
| S-8   | DONE        | Lint command — 5 checks, optional --save to lint-report.md           |
| S-8.5 | DONE        | Ingest CLI Orchestration — `tools/ingest.py` wrapping full pipeline. |
| S-9   | DONE        | Graph tool — build_graph.py, NetworkX, Louvain, vis.js, SHA256 cache |
| S-10  | DONE        | Query Tool (CLI MVP)                                                 |
| S-11  | NOT STARTED | Query --save implementation (future phase)                           |

---

## S-1 Outcomes

### What was built

| Module               | Purpose                                                                 |
|----------------------|-------------------------------------------------------------------------|
| `src/core/config.py` | Typed `Config` dataclass with `load_config()` and `load_env()`. Validates required fields, types, ranges, and cross-field constraints at startup. |
| `src/core/provider.py` | `select_provider()` with interactive prompt for `ask` mode. `check_lmstudio()` health check. `ensure_provider_ready()` retry loop with switch-to-Gemini escape hatch (AD-9). |
| `src/core/dirs.py`   | `ensure_directories()` creates vault and source subdirectories. Validates C-8 (sources outside vault) with case-insensitive path comparison for Windows. |
| `config.json`        | Default config file with all fields populated.                          |
| `.env.example`       | Template for `GEMINI_API_KEY`.                                          |
| `tests/unit/test_s1_foundation.py` | 46 unit tests (happy, edge, failure) per TDD contract. |
| `contracts/s-1-foundation.contract.md` | Full contract: APIs, data structures, boundary limits, test matrix. |
| `docs/decisions/s-1-foundation.md` | ADR: typed dataclass over plain dict for config loading. |

### Why

Every downstream slice (`S-2` through `S-9`) imports `src.core` for config, provider, and directory paths. Getting the foundation wrong would cascade failures across the entire codebase. TDD + contract-first ensured the boundary is well-defined and regression-proof.

### Assumptions validated

| ID   | Assumption                                               | Outcome                                     |
|------|----------------------------------------------------------|---------------------------------------------|
| A-2  | LM Studio exposes OpenAI-compatible `/v1` endpoint.      | Health check against `/v1/models` works.    |
| C-7  | API keys in `.env` only, never in source or config.      | `load_env()` reads from env/dotenv.         |
| C-8  | Sources directory outside the vault.                     | Enforced at directory init with `sys.exit`. |
| C-10 | Chunk thresholds configurable.                           | `Config` fields with range validation.      |

### Broken assumptions

None. No tracked assumption (A-1 through A-12) was invalidated during S-1.

Three implementation defects were found during post-implementation audit and fixed:

| Defect                                     | Severity | Fix applied                                                    |
|--------------------------------------------|----------|----------------------------------------------------------------|
| TOCTOU race in `ensure_directories`        | CRITICAL | Replaced `if not exists() → makedirs()` with `makedirs(exist_ok=True)`. |
| C-8 path check case-sensitive on Windows   | HIGH     | Replaced `str.startswith()` with `os.path.commonpath()` + `os.path.normcase()`. |
| `load_env()` blocks LM-Studio-only users   | HIGH     | Added `provider` parameter; `GEMINI_API_KEY` only required when `provider == "gemini"`. |

### Constraints honored

C-1 (Python only), C-3 (LM Studio endpoint configurable), C-4 (Gemini model configurable), C-7 (keys in env only), C-8 (sources outside vault), C-10 (thresholds configurable).

### Limitations discovered

| Item                                                                                     |
|------------------------------------------------------------------------------------------|
| `Config` dataclass is mutable (`frozen=True` not set). Acceptable for single-user CLI; revisit if config is ever shared across threads. |
| `check_lmstudio()` discards exception context (returns bare `False`). Sufficient for retry loop; add logging when observability layer exists. |
| `sys.exit(msg)` for validation failures means callers cannot catch and recover. Acceptable for CLI startup; revisit if config is ever loaded by a library consumer. |

### Next risks

| Risk                                                                                     | Mitigation                                     |
|------------------------------------------------------------------------------------------|-------------------------------------------------|
| S-2 (Source Extraction) introduces HTTP calls for URL fetch — first real network boundary beyond health check. | Define timeout, retry, and error contract before coding. |
| S-3 (LLM Layer) is the first consumer of `Config` chunking fields — if contract is wrong, chunks silently degrade synthesis. | Validate chunk sizes against actual token counts in S-3 tests. |
| No structured logging exists. S-2/S-3 failures will be harder to debug with only `print()`. | Consider adding `logging` module in S-2 or S-3. |

---

## S-2 Outcomes

### What was built

| Module               | Purpose                                                                 |
|----------------------|-------------------------------------------------------------------------|
| `src/core/extract.py` | Single dispatch function `extract_source(source)` routing to `_extract_url()`, `_extract_pdf()`, `_extract_text()`. Returns `(text, metadata)` tuple. Never returns empty text. |
| `tests/unit/test_s2_extraction.py` | 43 unit tests (happy, edge, failure) covering URL, PDF, text, and dispatch logic. |
| `contracts/s-2-source-extraction.contract.md` | Full contract: APIs, data structures, boundary limits, 43-test matrix. |
| `docs/decisions/s-2-source-extraction.md` | ADR: single dispatch function over strategy pattern. |

### Why

S-2 is the first real I/O boundary: HTTP calls for URLs, filesystem reads for PDFs and text files, and the optional Tesseract OCR binary. Getting error handling wrong here means silent empty text reaching the LLM in S-3, producing garbage wiki pages. The contract guarantees non-empty text on every success path.

### Assumptions validated

| ID   | Assumption                                               | Outcome                                     |
|------|----------------------------------------------------------|---------------------------------------------|
| A-5  | pdfplumber text extraction sufficient for text-native PDFs. | API works as expected; mocked in 43 tests. Remains ASSUMED until real PDFs tested. |
| C-11 | Tesseract installed separately, tool warns clearly.      | `TesseractNotFoundError` caught with actionable install instructions. |

### Broken assumptions

None. No tracked assumption (A-1 through A-12) was invalidated during S-2.

### Constraints honored

C-1 (Python only), C-11 (Tesseract external with actionable error), AD-6 (OCR gated behind 50-char threshold), AD-10 (sources read-only, never written).

### Limitations discovered

| Item                                                                                     |
|------------------------------------------------------------------------------------------|
| URL fetch has no retry logic. A transient network failure requires the user to re-run the command. Acceptable for MVP. |
| PDF OCR reopens the file with `pdfplumber.open()` a second time for page-to-image conversion. Minor I/O overhead, acceptable for typical document sizes. |
| Text file extraction loads entire file into memory. No streaming. Practical limit is available RAM. |
| Source type detection is heuristic (URL prefix, `.pdf` extension). A file named `notes.pdf` that is actually a text file would be misrouted to the PDF extractor and fail. |

### Next risks

| Risk                                                                                     | Mitigation                                     |
|------------------------------------------------------------------------------------------|-------------------------------------------------|
| S-3 (LLM Layer) is the first consumer of `extract_source()` output. If `char_count` in metadata doesn't correlate with token count, chunking decisions will be wrong. | S-3 should convert chars to tokens using a tokenizer, not use `char_count` directly. |
| No structured logging in S-2. URL fetch failures produce `SystemExit` with good messages, but no log file for post-mortem analysis. | Consider adding `logging` module in S-3. |
| Real PDF extraction (A-5) and real OCR quality (A-6) are still untested against actual documents. | Manual smoke test with real PDFs before S-4 integration. |

---

## S-3 Outcomes

### What was built

| Module               | Purpose                                                                 |
|----------------------|-------------------------------------------------------------------------|
| `src/core/chunking.py` | Pure functions: `chunk_text()` splits text with configurable overlap, `get_threshold_chars()` converts token thresholds to character thresholds, `get_overlap_chars()` converts token overlap to character overlap. |
| `src/core/llm.py`   | `complete()` dispatches to `_call_gemini()` or `_call_lmstudio()`. Handles chunking transparently. Both HTTP boundaries fully specified with timeouts, status codes, and provider-named error messages. |
| `tests/unit/test_s3_llm.py` | 43 unit tests (happy, edge, failure) covering chunking, Gemini completion, LM Studio completion, and dispatch validation. All HTTP calls mocked. |
| `contracts/s-3-llm-layer.contract.md` | Full contract: APIs, data structures, boundary limits, 43-test matrix. |
| `docs/decisions/s-3-llm-layer.md` | ADR: flat functions with `requests` over provider SDKs. |

### Why

S-3 is the first slice that calls LLMs. Every downstream slice (S-4 through S-7) uses `complete()` to transform extracted text into wiki content. Getting the HTTP boundary handling, chunking logic, or error reporting wrong here would cascade failures into page generation, batch proposal, and commit operations.

### Assumptions validated

| ID   | Assumption                                               | Outcome                                     |
|------|----------------------------------------------------------|---------------------------------------------|
| A-1  | `gemini-3-flash-preview` confirmed on free tier.        | API URL and payload format implemented. Remains CONFIRMED pending live smoke test. |
| A-2  | LM Studio OpenAI-compatible `/v1/chat/completions`.     | Payload format matches OpenAI spec. Remains CONFIRMED pending live smoke test. |
| A-3  | Qwen 3.5 9B handles 4k token chunks.                    | Chunking logic implemented with configurable threshold. Remains UNTESTED until real model inference. |

### Broken assumptions

None. No tracked assumption (A-1 through A-12) was invalidated during S-3.

### Constraints honored

C-1 (Python only), C-2 (Gemini + LM Studio only, validated in dispatch), C-3 (LM Studio endpoint from config), C-4 (Gemini model from config), C-7 (API key from env dict, never logged, never in error messages), C-10 (chunk thresholds configurable, converted via `_CHARS_PER_TOKEN`), AD-5 (provider-specific chunking with overlap).

### Limitations discovered

| Item                                                                                     |
|------------------------------------------------------------------------------------------|
| No retry/backoff on LLM calls. Gemini 429 or transient failures require the user to re-run. Acceptable per L-8. |
| Token-to-char heuristic (4 chars/token) is approximate. Non-English text or code may chunk suboptimally. Acceptable for MVP. |
| No streaming. Full response buffered in memory. Practical limit is available RAM for very large LLM responses. |
| `temperature = 0.7` is fixed. Not user-configurable in MVP. May need tuning for specific use cases. |
| No structured logging. LLM call failures produce `SystemExit` with descriptive messages but no log file. |

### Next risks

| Risk                                                                                     | Mitigation                                     |
|------------------------------------------------------------------------------------------|-------------------------------------------------|
| S-4 (Batch Proposal) is the first end-to-end consumer of S-2 + S-3. If prompt design doesn't produce well-structured wiki pages, the review loop will be painful. | Define system prompt contract in S-4 before coding. Test with real sources in smoke test. |
| A-3 (Qwen 3.5 9B chunk quality) is still UNTESTED. Multi-chunk synthesis may produce incoherent pages with LM Studio. | Manual smoke test with a real multi-chunk document before S-4 integration. |
| No structured logging across S-1/S-2/S-3. Debugging production issues requires reading `SystemExit` messages only. | Consider adding `logging` module in S-4 or as a cross-cutting concern. |

---

## S-4 Outcomes

### What was built

| Module               | Purpose                                                                 |
|----------------------|-------------------------------------------------------------------------|
| `src/core/proposal.py` | `PageProposal` and `Conflict` dataclasses. `slugify()` for deterministic kebab-case slug generation (AD-7). `resolve_collision()` with SHA256[:8] hash suffix. |
| `src/core/batch.py`  | `generate_batch()` — two-phase pipeline (plan then generate). Phase 1: LLM plans pages as JSON. Phase 2: LLM generates markdown per page. Reads index.md (AD-1), detects contradictions (AD-8), resolves slug collisions. Partial failure resilient. |
| `tests/unit/test_s4_batch.py` | 40 unit tests (happy, edge, failure) covering slug generation, wiki state reading, Phase 1 JSON parsing, conflict parsing, and batch orchestration. |
| `contracts/s-4-batch-proposal.contract.md` | Full contract: APIs, data structures, boundary limits, 40-test matrix. |
| `docs/decisions/s-4-batch-proposal.md` | ADR: two-phase pipeline over single-call batch generation. |

### Why

S-4 is the first slice to orchestrate extraction (S-2) and LLM (S-3) into structured wiki output. It produces the `PageProposal` dataclass that every downstream slice (S-5 through S-7) consumes. Getting the LLM interaction pattern, slug generation, or contradiction detection wrong here would cascade into broken review loops and corrupted wiki state.

### Assumptions validated

| ID   | Assumption                                               | Outcome                                     |
|------|----------------------------------------------------------|---------------------------------------------|
| A-4  | index.md navigation sufficient to ~300 pages.           | `_read_index()` reads index.md for Phase 1. Remains ACCEPTED. |
| A-9  | Kebab-case slugs rarely collide.                        | `slugify()` + `resolve_collision()` implemented with hash fallback. Remains ASSUMED until real ingestion. |
| A-10 | Single ingest touches ~15 pages.                        | Phase 2 makes N calls, bounded by this assumption. Remains ASSUMED. |

### Broken assumptions

None. No tracked assumption (A-1 through A-12) was invalidated during S-4.

### Constraints honored

C-1 (Python only), C-5 (wiki files markdown only), C-6 (wikilinks in system prompt), AD-1 (index.md read in Phase 1), AD-2 (no disk writes, in-memory batch), AD-7 (deterministic slugs with collision hash), AD-8 (LLM flags contradictions with `⚠️ CONFLICT:` markers).

### Limitations discovered

| Item                                                                                     |
|------------------------------------------------------------------------------------------|
| Phase 1 JSON parsing depends on LLM producing valid JSON. Code fences and leading/trailing prose are stripped, but deeply malformed output still causes `SystemExit`. |
| Contradiction detection is best-effort. The LLM may miss contradictions or produce false positives. S-5's review loop is the human safety net. |
| Phase 2 pages don't see each other's generated content. Cross-page coherence is limited to title-based wikilinks planned in Phase 1. |
| No structured logging. Phase 2 failures print warnings to stdout but leave no audit trail. |
| Slug dot handling: dots in titles (e.g., "3.1") are replaced with hyphens, producing slightly longer slugs ("3-1"). Acceptable for filesystem compatibility. |

### Next risks

| Risk                                                                                     | Mitigation                                     |
|------------------------------------------------------------------------------------------|-------------------------------------------------|
| S-5 (CLI Review Loop) is the first interactive slice. User input handling, editor integration ($EDITOR), and the reject/re-propose loop (AD-4) introduce new complexity. | Define contract with explicit input validation before coding. |
| Prompt quality is untested with real LLM responses. Phase 1 may produce unexpected JSON structures or hallucinated page titles. | Manual smoke test with real LLM before S-5 integration. |
| No structured logging across S-1 through S-4. Debugging production issues requires reading print() output and `SystemExit` messages only. | Consider adding `logging` module as cross-cutting concern. |

---

## S-5 Outcomes

### What was built

| Module / File | Purpose |
|---------------|---------|
| `src/core/review.py` | Implemented strict review-loop core APIs: `review_batch`, `validate_proposals`, `normalize_action`, `edit_content`, `collect_conflict_decisions`, `repropose_page`. |
| `src/core/review.py` | Added typed review structures: `ConflictDecision`, `ReviewEvent`, `ReviewResult` and strict boundary limits (batch size, retries, reject length, repropose cap). |
| `tests/unit/test_s5_review.py` | Added deterministic S-5 unit tests for happy/edge/failure review behaviors. Current result: `23 passed`. |
| `contracts/s-5-cli-review-loop.contract.md` | Added S-5 contract with API schemas, limits, failure semantics, and test matrix. |
| `docs/decisions/s-5-cli-review-loop.md` | ADR created and now updated to reflect implementation outcome and assumptions that broke. |

### Why

S-5 is the human safety gate between LLM-generated proposals and any future write path (S-7).
Strict validation and explicit action loops were prioritized to prevent silent acceptance of malformed proposals and to keep AD-4/AD-8 behavior deterministic.

### Assumptions

| ID | Assumption | Outcome |
|----|------------|---------|
| S5-A1 | Users may enter noisy action input; aliases and reprompts are enough for stable review flow. | Validated in tests (normalize + retry caps). |
| S5-A2 | `$EDITOR` may be missing; deterministic fallback is required. | Implemented (`nano` fallback) and tested. |
| S5-A3 | Reject/re-propose loops require an explicit upper bound. | Implemented (`_MAX_REPROPOSE_ATTEMPTS = 10`). |
| S5-A4 | Conflict decisions must be explicit per conflict before accepting updates. | Implemented and validated via conflict decision path tests. |

### Broken assumptions

| ID | Assumption broken | What actually happened | Impact | Resolution |
|----|-------------------|------------------------|--------|------------|
| S5-B1 | `PageProposal` from S-4 is always structurally valid when it reaches S-5. | S-4 allows `action="update"` plans without `existing_page`; S-5 requires non-empty `existing_path` for updates. | Integration can fail at review handoff despite S-4 success. | Keep S-5 strict validation; add follow-up rule to enforce `existing_page` for updates in S-4 parser. |

### Constraints

S-5 implementation honors:

- AD-2: no disk writes in review loop.
- AD-4: rejection loops through reproposal, not silent skip.
- AD-8: per-conflict user-directed resolution.
- C-9: system editor with fallback behavior.
- C-5/C-6: markdown/wiki-link-compatible content preserved as free text (no format conversion).

### Limitations

| Item |
|------|
| `tools/ingest.py` is still a stub, so S-5 is implemented as a core module but not yet wired into an executable CLI ingest path. |
| Review loop currently does not render true content diffs; it runs action flow/validation/edit/reproposal logic only. |
| Failures still use `SystemExit` in core modules, which limits reuse in non-CLI orchestration. |
| Structured observability for review events is not yet emitted to logs. |
| Contract matrix lists more cases than currently implemented tests (23 active tests), so full matrix coverage remains incomplete. |

### Next risks

| Risk | Mitigation |
|------|------------|
| S-6 edit propagation will increase coupling between review state and downstream proposal mutation. | Add focused unit tests for dependency-scoped propagation before wiring to ingest. |
| S-7 commit layer depends on clean, validated approved proposals; any schema drift at S-4/S-5 handoff will become write-path failures. | Enforce producer-side schema checks in S-4 before review handoff. |
| Path traversal risk remains in S-4 update-page loading from LLM-provided `existing_page` values. | Add vault-path containment validation before file reads in S-4. |
| Lack of end-to-end CLI integration hides operational failures until later slices. | Wire `tools/ingest.py` as next critical integration step before S-6/S-7 hardening. |

---

## Unresolved Items

> ⛔ No items currently block progress.

| ID   | Item                          | Resolution                                                          |
|------|-------------------------------|---------------------------------------------------------------------|
| UR-1 | Gemini model                  | `gemini-3-flash-preview`. Free tier confirmed. Released Dec 2025.   |
| UR-2 | Scanned PDF handling          | OCR via Tesseract. Auto-detected; user notified when triggered.     |
| UR-3 | LM Studio not running         | Retry prompt. Offer switch-to-Gemini escape hatch.                  |
| UR-4 | Wiki scale ceiling            | Soft warning at 300 pages. Accepted as known limitation L-1.        |
| UR-5 | Contradiction resolution UX   | Per-conflict: update in place OR append conflict note.              |
| UR-6 | Page naming convention        | LLM-generated title → deterministic kebab-case slug.                |
| UR-7 | Graph implementation          | NetworkX + Louvain + vis.js. graph.html, SHA256 cache, 3 edge types.|
|      |                               | Reference: SamurAIGPT/llm-wiki-agent build_graph.py.                |
| UR-8 | Query --save design           | Pre-decided: save answer as wiki page at user-specified path.       |
|      |                               | Implementation deferred to S-11.                                    |

---

## S-8 Outcomes

### What was built

| Module               | Purpose                                                                 |
|----------------------|-------------------------------------------------------------------------|
| `src/core/lint.py` | Implementation of 5 wiki health checks: orphans, broken links, duplicate slugs, empty pages, stale index. Defines `LintIssue` and `LintReport` dataclasses. |
| `tools/lint.py` | CLI wrapper calling `run_all_checks`. Optionally writes `vault/wiki/lint-report.md`. |
| `tests/unit/test_s8_lint.py` | 11 deterministic unit tests covering happy path, explicit file exclusions, limit bounding, and format semantics. |
| `contracts/s-8-lint-command.contract.md` | Contract for domain validation, data interfaces, and bounding scopes. |
| `docs/decisions/s-8-lint-command.md` | ADR: strict CLI and Domain separation, on-demand synchrony. |

### Why

Wiki pages are created and managed automatically. As the vault grows, dead pages (orphans), broken wiki references, and stale index states can occur manually or from interrupted syncs. S-8 provides a quick deterministic observation layer to maintain wiki health without utilizing LLM inference.

### Assumptions validated

| ID   | Assumption                                               | Outcome                                     |
|------|----------------------------------------------------------|---------------------------------------------|
| A-4  | index.md-based navigation.                               | Enforced locally: index-staleness check successfully cross-references actual pages vs index without traversing relationships. |

### Broken assumptions

None. No global tracked assumption (A-1 through A-12) was invalidated. An ADR local assumption was explicitly refined to not only exclude bookkeeping files from the 'orphan' target list, but also securely sever bookkeeping files from supplying inbound links to normal files.

### Constraints honored

C-1 (Python only), C-5 (validate markdown structure/wikilinks only), C-6 (Regex `\[\[([^\]]+)\]\]` handles standard link syntax), AD-7 (Kebab-case slug equivalence matching).

### Limitations discovered

| Item                                                                                     |
|------------------------------------------------------------------------------------------|
| Synchronous memory bounding limits scalability: fetching all file contents continuously into memory creates memory/time complexity of O(N^2) against links. Acceptable given L-1 soft-boundary of ~300 pages. |
| Orphan rule rigidly skips bookkeeping files. Subtly isolates `index.md` as entirely structurally unbound, requiring humans to understand orphaned pages naturally not linked natively inside texts. |

### Next risks

| Risk                                                                                     | Mitigation                                     |
|------------------------------------------------------------------------------------------|-------------------------------------------------|
| S-9 (Graph tool) relies on parsed structure mappings mirroring actual page availability. Broken wikilinks may crash graph generations or produce ghost clusters. | S-9 must robustly fall back when graph targets fail, or user should be prompted to run `tools/lint.py`. |

---

## S-8.5 Outcomes

### What was built

| Module               | Purpose                                                                 |
|----------------------|-------------------------------------------------------------------------|
| `src/core/ingest.py` | Orchestrator module strictly wrapping `load_config`, `extract`, `generate_batch`, `review_batch`, `propagate_edits`, and `commit`. |
| `tools/ingest.py`    | Thin CLI dispatch stub trapping unhandled exceptions. |
| `src/core/review.py` | (Modified) Added `on_edit_callback` allowing dynamically bubbling `propagate_edits` routines without terminating standard iterative review loops natively. |

### Why

The project previously constructed isolated modular domains. Operating them interactively required a stable, synchronized single-call sequence executable from the CLI without risking logic drifting, variable desyncing, or unbounded user waiting states natively during batch processing.

### Assumptions validated

None directly. We assumed native exception catching of domains (e.g. `SystemExit` for handled fails like OCR missing) would operate elegantly at the orchestration root, requiring no complex Try/Catch trees internally. Tested successfully.

### Broken assumptions

None newly discovered, but the structural coupling in S-5/S-6 dictated that `propagate_edits()` could not natively execute safely from within the core batch reviewer loop `src/core/review.py` without risking scope creep. We passed it cleanly via callbacks.

### Constraints honored

C-1 (Python only wrapper). No external framework requirements injected for orchestration state machine.

### Limitations discovered

| Item                                                                                     |
|------------------------------------------------------------------------------------------|
| Linear console output handling natively scales linearly causing terminal wall-of-text blocks if the user processes massive 20+ batch arrays during Editor loops. |

### Next risks

| Risk                                                                                     | Mitigation                                     |
|------------------------------------------------------------------------------------------|-------------------------------------------------|
| S-9 Graph logic relies upon structurally predictable files. The pipeline is fully established, meaning any graph implementation bug moving forward sits squarely within `vis.js` and `NetworkX` handling bounds, isolated safely away from generation. | Future passes must strictly filter `.json` edges to completely omit ghost node parameters gracefully preventing UI crashes. |

---

## S-9 Outcomes

### What was built

| Module               | Purpose                                                                 |
|----------------------|-------------------------------------------------------------------------|
| `src/core/graph.py`  | Executes `networkx` mapping and partitions via `python-louvain` connecting structural wikilinks and semantic LLM queries via cache buffers. |
| `tools/build_graph.py` | CLI endpoint exposing `--no-infer` handling and explicit `--open` visual triggers mapping outputs securely. |

### Why

Building the final offline analytics capability ensures the LLM wiki acts not just as raw document storage, but inherently maps community topic clusters securely offline without dependency on cloud rendering dashboards.

### Assumptions validated

Native `vis.js` CDN logic loads locally injected JSON efficiently handling physical DOM bounds reliably during standard load constraints. 

### Broken assumptions

The architectural assumption that a blocking run bounds LLM cache structures identically to batch creation failed. If generation times out due to LLM rate limits at scale, cache variables aren't written until termination completes—meaning execution wipes progressive progress locally.
*(No ADR update required inherently since the base selection approach remained B, but this alters standard enterprise adoption expectations natively.)*

### Constraints honored

C-12 fulfilled precisely utilizing NetworkX and standard `vis-network.min.js`. Fully local Python-only codebase maintained securely natively avoiding external build compilers.

### Limitations discovered

| Item                                                                                     |
|------------------------------------------------------------------------------------------|
| **Ghost Nodes**: Extracted and Semantic edges mapped locally without cross-examining physical vault node existence inherently crash vis.js rendering DOM algorithms. |
| **Silent Block**: API blocks offer 0 logging natively, meaning the user sits indefinitely without generation bounding awareness. |
| **Cache Deletion**: Uncaught timeouts mid-execution completely dump identical previous outputs failing to append intermediate chunks sequentially. |

### Next risks

| Risk                                                                                     | Mitigation                                     |
|------------------------------------------------------------------------------------------|-------------------------------------------------|
| S-10 Web UI will rely on these `.json`/`.html` models to function correctly. If the UI pulls broken links natively, frontend routers will throw identical structural errors heavily. | Future architectural passes require strict target node filtration logic natively inside `edges_data` mappings. |

---

## S-10 Outcomes

### What was built

| Module               | Purpose                                                                 |
|----------------------|-------------------------------------------------------------------------|
| `src/core/query.py`  | Orchestrates a two-hop "planner and synthesizer" LLM loop to parse the wiki natively without a vector database. |
| `tools/query.py`     | CLI wrapper capturing user questions natively gracefully declining `--save` parameters mapping Read-Only behavior. |

### Why

Enabled direct natural language interactions with the Wiki's contents. Building a vector DB abstraction was explicitly forbidden in the anti-goals; therefore, we required a sophisticated 2-hop LLM router strictly bound securely to offline file extraction to answer questions deterministically relying strictly on the existing `index.md`.

### Assumptions validated

Two-Hop architecture functions perfectly on small scale bounds allowing strict structural extraction of top `N` targets directly formatting synthesis gracefully. 

### Broken assumptions

The architectural bounds implicitly assumed `MAX_FILE_CHARS = 10000` iteratively extracted over exactly `3` files would strictly remain underneath memory allocations natively. The math failed cleanly: `30,000` chars inherently scales drastically upwards past ~7,500 tokens entirely destroying the strict Qwen LM Studio 4,000 ceilings.
*ADR Update Required*: Modifying the ADR directly is unnecessary as Two-Hop remains structurally the only solution natively—but the string parameters will absolutely require future truncations strictly mapped down locally. 

### Constraints honored

Strictly avoided embeddings. Strictly avoided external databases. `index.md` used natively as the only map constraints reliably conforming to `PROJECT_BRIEF.md` anti goals constraints. 

### Limitations discovered

| Item                                                                                     |
|------------------------------------------------------------------------------------------|
| **Path Traversal Inject**: Hop 1 JSON payloads inherently evaluate directly without natively checking `resolve().is_relative_to(wiki_path)` generating critical local file read vulnerability endpoints natively. |
| **Index Truncation**: Chopping `index.md` exactly at 30,000 characters immediately blinds the tool completely to categorical scales mapping documents lower in alphabetical structures. |

### Next risks

| Risk                                                                                     | Mitigation                                     |
|------------------------------------------------------------------------------------------|-------------------------------------------------|
| Running Phase 2 `S-12 Query --save` dynamically passing un-sanitized Path Strings directly into Phase 4 Write components could potentially overwrite critical physical `.git` bounds maliciously bypassing bounds. | S-12 mapping must inherently include physical sanitize validation locks natively restricting extraction targets gracefully preventing structural collapses natively. |

