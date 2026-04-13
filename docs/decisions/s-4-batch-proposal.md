# ADR: Batch Proposal Architecture

| Field   | Value                                                    |
|---------|----------------------------------------------------------|
| Slice   | S-4                                                      |
| Date    | 2026-04-12                                               |
| Status  | ACCEPTED                                                 |
| Decides | How source text is transformed into an in-memory batch of page proposals |

---

## Context

S-4 is the first slice to orchestrate S-2 (extraction) and S-3 (LLM calls) into
structured wiki output. It consumes extracted source text and produces an ordered
list of `PageProposal` objects that S-5 (review loop) presents to the user.
Nothing is written to disk (AD-2).

**Binding constraints:**
- AD-1: LLM reads index.md to map existing wiki.
- AD-2: Batch-then-commit. All proposals collected in-memory before review.
- AD-7: Deterministic kebab-case slug from LLM-generated title, collision hash.
- AD-8: Contradiction detection. LLM flags conflicts with existing pages.
- C-5: Wiki files markdown only.
- C-6: Obsidian `[[wikilinks]]` syntax required.

**Provider asymmetry:** Gemini has 1M token context (~4M chars). LM Studio has
4k token context (~16k chars). Any architecture must work with both.

---

## Approach 1 — Single-call batch generation (JSON response) [REJECTED]

One call to `complete()` with full context (index.md + source text + existing
pages). System prompt instructs LLM to return a JSON array of all page proposals
including content and contradiction flags.

**Why rejected:**
- LM Studio's 4k context makes single-call impractical. S-3's `complete()`
  chunks the prompt, but chunking a "return a JSON array of all pages" prompt
  produces fragmented, unparseable results.
- JSON parsing of large LLM output is fragile. LLMs frequently emit malformed
  JSON, markdown fences, or extra prose around the array.
- A single failure (timeout, empty response) loses the entire batch with no
  partial recovery.
- Violates ENGINEERING.md: "Systems fail at boundaries" — a monolithic call
  has one boundary with many failure modes.

## Approach 2 — Two-phase pipeline (plan then generate) [CHOSEN]

**Phase 1 (Plan):** Call `complete()` with index.md + source text. LLM returns
a small JSON list: `[{title, action, category}]`. Short, focused output.

**Phase 2 (Generate):** For each planned page, call `complete()` with source
text + existing page content (if update) + all planned titles. LLM returns
markdown content. Contradictions detected via inline markers.

**Strengths:**
- LM Studio friendly. Phase 1 prompt is small. Phase 2 prompts are per-page.
- Phase 1 is a short JSON list — robust to parse even with LLM quirks.
- Phase 2 is per-page. A failure on page 3 doesn't lose pages 1, 2, 4, 5.
- Each phase is independently testable.
- Consistent with established codebase pattern: flat functions, `complete()`.

**Weaknesses:**
- More API calls (1 + N). Bounded by A-10 (~15 pages).
- Phase 2 pages don't see each other's generated content.

---

## Why Approach 2 wins

1. **Works with both providers.** LM Studio's 4k context makes single-call
   impractical. Phase-based keeps each call's context focused.
2. **Partial failure resilience.** Page generation failures are caught and
   skipped. Successful pages survive.
3. **Phase 1 is small JSON, Phase 2 is free-form markdown.** JSON parsing is
   confined to the compact planning response. Page content has no structural
   parsing — just conflict marker extraction.
4. **Consistent with S-1/S-2/S-3.** Flat functions, `_fail()`, `complete()`.
5. **A-10 bounds the cost.** ~15 pages = ~16 LLM calls. Acceptable.

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Two modules: `proposal.py` (data) + `batch.py` (orchestration) | Data structures consumed by S-5, S-6, S-7. Separate module avoids circular imports. |
| `slugify()` + `resolve_collision()` with SHA256[:8] | Deterministic per AD-7. Short hash sufficient for <300 pages (A-4). |
| Phase 1 JSON parsing strips code fences and prose | LLMs commonly wrap JSON in triple-backtick fences. Robustness measure. |
| Conflict markers are LLM-generated, not computed diffs | Semantic contradictions require LLM judgment. String diffing is insufficient. |
| Empty batch is a valid outcome, not an error | Source text may not warrant any wiki pages. Caller handles the empty list. |
| Phase 2 failures are warnings, not fatal | Partial batch is better than no batch. |

---

## Consequences

1. `generate_batch()` is the single entry point for proposal generation.
   S-5+ calls it with provider, config, env, source text, and metadata.
2. `PageProposal` is the contract between S-4 and S-5. All downstream slices
   consume this dataclass.
3. Slug generation is deterministic and collision-safe. The same title always
   produces the same base slug.
4. Contradiction detection is best-effort. The LLM may miss contradictions or
   generate false positives. S-5's review loop is the human safety net.
5. No disk writes. Everything is in-memory until S-7 commits.

---

## ENGINEERING.md Checklist

| Principle              | Application                                                    |
|------------------------|----------------------------------------------------------------|
| Explicit > implicit    | Two-phase pipeline is explicit. Categories and actions are closed enums. Slug generation is deterministic. |
| Simple > clever        | Flat functions. Two modules. No class hierarchy. No strategy pattern. |
| Contracts define behavior | Contract doc defines every API, JSON schema, conflict marker format. |
| Fail fast and clearly  | `SystemExit` on Phase 1 failure. `ValueError` on invalid slug. Empty source caught before LLM call. |
| Validate all inputs    | Phase 1 JSON validated field-by-field. Source text validated non-empty. |
| Never swallow errors   | Phase 2 failures print warnings naming the failed page. |
| Systems fail at boundaries | Phase 1 JSON is untrusted. Missing files return "" gracefully. |
