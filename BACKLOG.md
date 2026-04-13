# BACKLOG.md — LLM Wiki

_Last updated: 2026-04-12_
_Source of truth for slice status. Derived from PROJECT.md Slice History._

---

## Status Key

- `[ ]` — todo
- `[~]` — in-progress
- `[x]` — done
- `[!]` — blocked

---

## Slices

### S-0: Requirements Interview `[x]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | Capture user intent, constraints, and scope in a frozen brief.        |
| Inputs       | User interview (conversational).                                      |
| Output       | `PROJECT_BRIEF.md` — frozen intent document.                          |
| Done-when    | PROJECT_BRIEF.md exists and is marked frozen. No open questions.      |
| Dependencies | None.                                                                 |

---

### S-0.5: Project Specification `[x]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | Resolve all open items from the brief into concrete decisions.        |
| Inputs       | `PROJECT_BRIEF.md`, user clarifications.                              |
| Output       | `PROJECT.md` — live source of truth with ADs, constraints, assumptions.|
| Done-when    | All unresolved items have resolutions. PROJECT.md is marked ready.    |
| Dependencies | S-0.                                                                  |

---

### S-0.6: Graph Stack & Chunking Rev `[x]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | Lock graph implementation stack and update chunking thresholds.       |
| Inputs       | Research on NetworkX/Louvain/vis.js. SamurAIGPT reference repo.       |
| Output       | PROJECT.md rev 2 — AD-12 graph stack, AD-5 thresholds finalized.      |
| Done-when    | AD-5 and AD-12 are complete. No `[UNRESOLVED]` tags remain.          |
| Dependencies | S-0.5.                                                                |

---

### S-1: Foundation `[x]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | Bootstrap runtime config, directory creation, and provider selection. |
| Inputs       | `config.json` schema definition, `.env` key names.                    |
| Output       | `config.json` loader with validation. Directory initializer for `vault/wiki/{sources,entities,concepts}`, `vault/graph/`, `sources/{articles,pdfs,notes}`. Provider selector (Gemini / LM Studio) with LM Studio health check + retry/switch (AD-9). |
| Done-when    | 1. `config.json` loads and validates required fields (vault path, sources path, provider, chunk thresholds). Missing field → hard fail with field name. 2. `.env` loads API keys; missing key → hard fail naming the key (C-7). 3. Directories are created if absent. 4. Provider selection returns a configured provider object. 5. LM Studio ping fails → retry prompt → "switch" → Gemini fallback works. |
| Dependencies | None.                                                                 |

---

### S-2: Source Extraction `[x]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | Convert raw sources (URL, PDF, text) into plain text for LLM.        |
| Inputs       | Source path or URL from CLI argument.                                  |
| Output       | `(text: str, metadata: dict)` tuple per source. Metadata: source path, extraction method, timestamp, token count. |
| Done-when    | 1. URL extractor fetches page, strips HTML, returns text. Unreachable URL → clear error, no empty text downstream. 2. PDF extractor returns text via pdfplumber. Scanned PDF (below char threshold) → Tesseract OCR auto-triggers with user notification (AD-6). Tesseract missing → actionable error naming the dependency (C-11). 3. Text/markdown reader returns file contents. Missing file → clear error. 4. No extractor ever returns empty text silently. |
| Dependencies | S-1 (config for source paths).                                        |

---

### S-3: LLM Layer `[x]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | Unified LLM interface: prompt → structured response, with chunking.  |
| Inputs       | Provider config (from S-1). Extracted text (from S-2). System/user prompt templates. |
| Output       | Provider abstraction with `complete(system_prompt, user_content) → structured response`. Chunking engine that splits text at provider threshold (4k LM Studio / 750k Gemini per AD-5) with overlapping boundaries. |
| Done-when    | 1. Gemini client sends prompt, receives response, parses it. API key missing → fail fast. 2. LM Studio client sends prompt to `localhost:1234/v1/chat/completions`, receives response. 3. Chunking splits text only when token count exceeds threshold. Chunks overlap at boundaries. Single chunk when under threshold. 4. Both providers return identical response schema to callers. Provider swap is invisible to upstream code. |
| Dependencies | S-1 (provider config, API keys). S-2 (extracted text as input).       |

---

### S-4: Batch Proposal Engine `[x]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | Generate proposed wiki page operations from extracted source text.    |
| Inputs       | Extracted text + metadata (S-2). LLM provider (S-3). Existing `vault/wiki/index.md`. Existing wiki pages (read-only). |
| Output       | Ordered list of `PageProposal(title, slug, content, conflicts[], action: create\|update)`. In-memory batch — nothing on disk. |
| Done-when    | 1. LLM reads `index.md` to map existing wiki. Relevant existing pages loaded for context. 2. LLM proposes new/updated pages. Each proposal has title, content with `[[wikilinks]]` (C-6), and action type. 3. Slug derived from title as deterministic kebab-case (AD-7). Collisions resolved with short hash. 4. Contradiction detection: proposed content diffed against existing pages. Conflicts flagged with source reference (AD-8). 5. Empty batch (LLM proposes nothing) → clean "no pages proposed" exit. |
| Dependencies | S-2, S-3. Vault must exist (S-1).                                    |

---

### S-5: CLI Review Loop `[x]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | Interactive per-page review: display, edit, accept/reject, conflict resolution. |
| Inputs       | Batch of `PageProposal` objects (S-4). `$EDITOR` env var (C-9).       |
| Output       | Approved batch: subset of proposals the user accepted (possibly edited). |
| Done-when    | 1. Each proposal displayed sequentially with diff (new content or delta). 2. User can open page in `$EDITOR`; fallback to `nano` if unset (C-9). Edits captured on save. 3. Accept → proposal moves to approved set. 4. Reject → user enters reason → LLM re-proposes incorporating reason (AD-4). Loop continues until accept or explicit abandon. 5. Conflicts shown per-conflict with two options: update-in-place or append-conflict-note (AD-8). User picks per conflict. 6. Abandoning all pages → clean exit, nothing committed. |
| Dependencies | S-4 (batch input). S-3 (LLM for re-proposal on reject).              |

---

### S-6: Edit Propagation `[x]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | Re-evaluate downstream pages when user edits an upstream page.       |
| Inputs       | Edited page content. Remaining unreviewed proposals. Wikilink dependency graph (in-batch). |
| Output       | Updated proposals for pages that depend on the edited page.           |
| Done-when    | 1. When user edits page A, system identifies all unreviewed proposals containing `[[Page A]]` wikilinks. 2. Only those dependent pages are sent to LLM for re-evaluation — not the full batch (AD-3). 3. Re-evaluation is sequential and blocking. User waits. 4. Re-evaluation failure → keep original proposal, warn user. 5. Pages with no dependency on the edited page are untouched. |
| Dependencies | S-5 (review loop triggers propagation). S-3 (LLM for re-evaluation). |

---

### S-7: Commit Layer `[x]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | Atomic write of approved batch to vault. Update bookkeeping files.   |
| Inputs       | Approved batch (from S-5/S-6). Vault path (from S-1 config).         |
| Output       | Wiki pages written to `vault/wiki/{category}/{slug}.md`. `index.md` regenerated. `log.md` appended. |
| Done-when    | 1. Each approved page written to correct category subdirectory. 2. `index.md` fully regenerated to reflect all current wiki pages (AD-11, auto-committed). 3. `log.md` appended with operation record: timestamp, source, pages created/updated (AD-11). 4. Write failure mid-batch → full rollback of all writes from this batch. Vault returns to pre-commit state (AD-2). 5. Successful commit → summary printed to terminal (pages written, conflicts resolved). |
| Dependencies | S-5, S-6 (approved batch). S-1 (vault path).                         |

---

### S-8: Lint Command `[x]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | On-demand wiki health checks via `python tools/lint.py`.             |
| Inputs       | All files in `vault/wiki/`. `index.md` for cross-reference.           |
| Output       | Terminal report listing issues by check. `--save` writes `vault/wiki/lint-report.md`. |
| Done-when    | 1. Orphan check: pages with zero inbound `[[wikilinks]]` flagged. 2. Broken link check: `[[Target]]` where target page doesn't exist. 3. Duplicate slug check: two files resolving to same slug. 4. Empty page check: pages with no meaningful content. 5. Index staleness check: `index.md` entries vs. actual files on disk. 6. Terminal output lists issues grouped by check type with file paths. 7. `--save` writes identical report to `vault/wiki/lint-report.md`. 8. Clean wiki → "No issues found" message. |
| Dependencies | S-7 (wiki must have pages to lint). S-1 (vault path config).         |

---

### S-8.5: Ingest CLI Orchestration `[x]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | Wire core modules (S-1 through S-7) into `tools/ingest.py`.           |
| Inputs       | CLI `source` target argument.                                         |
| Output       | Standard output of the interactive ingestion pipeline.                |
| Done-when    | 1. `python tools/ingest.py <source>` runs the tool end-to-end interactively. 2. Integrates extraction, batch planning, CLI review loop, propagation, and commit smoothly. 3. Gracefully catches `SystemExit` for managed exit codes. |
| Dependencies | S-1 through S-7.                                                      |

---

### S-9: Graph Tool `[x]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | Build interactive knowledge graph from wiki pages.                   |
| Inputs       | All files in `vault/wiki/`. Existing `vault/graph/graph.json` cache. LLM provider (for inference). |
| Output       | `vault/graph/graph.json` (node/edge data with SHA256 hashes). `vault/graph/graph.html` (self-contained vis.js viewer). |
| Done-when    | 1. SHA256 hash per wiki page compared against `graph.json` cache. Unchanged pages skipped. 2. `EXTRACTED` edges parsed from `[[wikilinks]]` in page content (C-6). 3. Without `--no-infer`: LLM detects `INFERRED` edges with confidence 0–1. Below-threshold edges marked `AMBIGUOUS`. 4. With `--no-infer`: only structural edges, no LLM calls. Fast rebuild. 5. NetworkX graph built. Louvain community detection assigns topic clusters. 6. `graph.json` serialized with nodes, edges, clusters, hashes. 7. `graph.html` generated: self-contained, loads vis.js from CDN (C-12), reads `graph.json`, renders interactive graph (C-13). 8. `--open` opens `graph.html` in default browser. |
| Dependencies | S-7 (wiki pages must exist). S-3 (LLM for inference). S-1 (config).  |

---

### S-10: Query Tool (CLI MVP) `[x]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | Read-only CLI lookups.                                               |
| Inputs       | `"question string"`                                                   |
| Output       | Standard out console.                                                 |
| Done-when    | Returns mapped LLM completions.                                       |
| Dependencies | S-1, S-3                                                              |

---

### S-11: Web UI `[ ]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | Browser-based interface for wiki management. Future phase.           |
| Inputs       | TBD.                                                                  |
| Output       | TBD.                                                                  |
| Done-when    | TBD. Not scoped for MVP.                                              |
| Dependencies | S-1 through S-9 (full CLI pipeline).                                  |

---

### S-12: Query --save `[ ]`

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| Purpose      | Save query answers as first-class wiki pages. Future phase.          |
| Inputs       | Query answer text. `--save` or `--save <path>` flag. Vault path.      |
| Output       | New wiki page at specified path (or prompted). `index.md` updated.    |
| Done-when    | 1. `--save` without path → prompt user for category and title. 2. `--save <path>` → write directly. 3. Saved page goes through standard approval (user reviews before write). 4. `index.md` and `log.md` updated (AD-11). Interface matches AD-13 design. |
| Dependencies | S-7 (commit layer). S-3 (LLM for query). Query MVP from ingest pipeline. |

---

## Dependency Graph

```
S-0 → S-0.5 → S-0.6
                 │
                 ▼
                S-1 (Foundation)
               / | \
              /  |  \
             ▼   ▼   ▼
           S-2  S-8  S-9
            │         ▲
            ▼         │
           S-3 ───────┤
           / \        │
          ▼   ▼       │
        S-4  (query)  │
          │           │
          ▼           │
        S-5           │
          │           │
          ▼           │
        S-6           │
          │           │
          ▼           │
        S-7 ──────────┘
          │
          ├──► S-10 (future)
          └──► S-11 (future)
```

---

## Progress Summary

| Status | Count | Slices                        |
|--------|-------|-------------------------------|
| `[x]`  | 14    | S-0, S-0.5, S-0.6, S-1, S-2, S-3, S-4, S-5, S-6, S-7, S-8, S-8.5, S-9, S-10 |
| `[~]`  | 0     |                               |
| `[ ]`  | 2     | S-11, S-12                    |
| `[!]`  | 0     |                               |
