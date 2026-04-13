# System Integration & Simulation Trace

This document maps the end-to-end integration boundaries of the LLM Wiki system, tracing data flow from source ingestion through the LLM pipeline down to vault commit. It identifies the operational coupling, strict architectural mismatches, and major cascading failure points under stress.

---

## 1. Data Flow Trace

The primary ingestion boundary operates as a linear, synchronously blocked pipeline orchestrated by `src/core/ingest.py`.

1. **Extraction (S-2):** `(source_location)` → `extract_source()` → `(source_text, source_meta)`
   - Pure read boundary. Data flows from external URLs or files into memory. 
2. **Generation (S-3/S-4):** `(source_text)` → `generate_batch()` → `list[PageProposal]`
   - Reads `vault/wiki/index.md` statically for context.
   - Triggers chunking and multiple LLM calls. Mutates unstructured text into structured dataclasses with action intents (`create`, `update`).
3. **Review Loop (S-5):** `list[PageProposal]` → `review_batch()` → `list[PageProposal]`
   - Interactive loop. Pauses execution waiting for terminal `stdin`.
   - Modifies `PageProposal.content` via subprocess to `$EDITOR`.
   - Modifies state inside the list via `repropose_page()` (triggers new synchronous LLM calls).
4. **Edit Propagation (S-6):** `on_edit_callback` → `propagate_edits()` → `list[PageProposal] (pending slice)`
   - Dynamically re-writes the downstream `remaining_pending` array elements when an upstream proposal is edited by the user.
5. **Commit (S-7):** `list[PageProposal] (approved)` → `commit_approved_batch()` → `Disk Writes`
   - Flushes memory models to disk. Writes new markdown files, applies diffs to update pages, and rewrites `index.md`/`log.md`.

---

## 2. Integration Mismatches

These are areas where data contracts between S-slices actively drift or fight each other:

- **S-4 vs S-5 Validation Handoff (BA-1):** `generate_batch` allows the LLM to output an `action="update"` without specifying an `existing_page` path. However, `review_batch()` actively enforces strict Pydantic-like validations where `existing_path` must not be empty for updates. This mismatch means a successful LLM batch generation can instantly crash when handed to S-5.
- **S-8/S-9 vs S-4 (Ghost Nodes):** S-4 generation relies heavily on the LLM injecting `[[Wikilink]]` strings into the body text. If the LLM hyphenates a page differently than the derived `slug`, S-8 Linting flags it as a broken link, and S-9 Graph Tool crashes the `vis.js` visualization because the target graph node physically doesn't exist in the JSON.
- **S-10 Query vs S-3 Chunk Limits:** S-10 passes up to 30,000 characters (approx. 7,500 tokens) of `index.md` continuously to the LLM. But the S-3 local provider setup (`LM Studio / Qwen 3.5`) has a firm 4,000 token context window. S-10 routinely violates the system's own configured boundary thresholds.

---

## 3. Structural Coupling

- **Edit Propagation (S-5/S-6):** The Review engine `review.py` is structurally decoupled from S-6 via a generic `on_edit_callback`, but logically they are tightly bound. `propagate_edits` inherently assumes the structure of the remaining `list[PageProposal]`. Because lists are passed and replaced iteratively, any bug in the callback slice logic will truncate or corrupt the un-reviewed queue entirely.
- **Shared Mutable `Config`:** The `Config` dataclass initialized in S-1 is globally mutable. It is passed down through every layer: Extraction, Generate, Review, Propagate. Any module could accidentally mutate `config.chunk_size_tokens` mid-run, quietly altering downstream LLM constraints.
- **Index Reliance:** `generate_batch` (S-4), `lint` (S-8), and `query` (S-10) all treat `index.md` as their single source of truth for the vault state. They are completely decoupled from actual filesystem traversal, creating high dependency coupling on `S-7 Commit` formatting the index string identically every time.

---

## 4. Cascading Failure Points

If this system is deployed as-is, the following system-breaking failures will trigger under normal operational loads:

1. **The Terminal Hostage Crisis (Timeout Cascade)**
   - **Simulation:** A batch generates 35 pages. The user edits Page #1. S-6 `propagate_edits()` intercepts the array and kicks off 34 sequential synchronous LLM calls to check for downstream dependency impacts.
   - **Impact:** The CLI blocks for 3 to 10 minutes. If the Gemini Free Tier Rate Limit (429) triggers on page #28, `src/core/llm.py` throws a raw exception. The exception bubbles to `sys.exit` in `tools/ingest.py`. The **entire batch** (and the S-2 extraction) is wiped from memory. The user's edit on Page #1 is permanently lost.
2. **Race Condition at Commit (Stale Reads)**
   - **Simulation:** A user starts `tools/ingest.py` on a large PDF, going into the S-5 Review Loop. At the same time, the user runs `tools/query.py` or a background S-9 Graph job in another terminal. S-5 completes and `commit` begins overwriting `index.md` while S-10 is attempting to `read_text()` the exact same file.
   - **Impact:** Torn reads/writes. The Query tool crashes on malformed text, or worse, `commit` drops index file byte allocations entirely.
3. **Ghost Writes on Reproposal**
   - **Simulation:** During S-5, the user rejects a page and enters a reason. `repropose_page()` sends a new LLM request. The API drops the connection mid-generation. 
   - **Impact:** Because there is zero retry logic inside S-5's interaction with `complete()`, the connection timeout forces a hard panic (`SystemExit`). Over an hour of careful review approvals sitting in the `approved` array memory evaporates instantly because S-7 `commit` is structurally deferred until the loop halts successfully. 
4. **Out of Memory Exhaustion (OOM)**
   - **Simulation:** `query_wiki` or `extract_pdf` reads a file using un-paginated `read_text()[:MAX_LIMIT]`. 
   - **Impact:** The Python interpret allocates the entire file into physical RAM before applying the slice delimiter. A misplaced 5GB core dump or large video masquerading locally will instantly OS-kill the application.
