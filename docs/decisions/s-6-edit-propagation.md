# ADR: Edit Propagation Architecture

| Field | Value |
|---|---|
| Slice | S-6 |
| Date | 2026-04-12 |
| Status | PROPOSED |
| Decides | How edit propagation handles downstream dependency updates in the batch |

---

## Re-read Project Files
Reviewed before planning:
- `PROJECT.md` (AD-2, AD-3, Constraints)
- `BACKLOG.md` (S-6 status and acceptance criteria)
- `contracts/s-6-edit-propagation.contract.md` (API contracts, test specs)
- `agents/skills/ENGINEERING.md` (Strict boundaries, fail fast, predictable behavior)

---

## Goal (Restated)
Re-evaluate downstream pages systematically when a user edits an upstream page during batch review.
The re-evaluation should:
1. Target *only* unreviewed proposals that explicitly link to the edited page (e.g. `[[Page Title]]`).
2. Happen sequentially and strictly blocking.
3. Be failure-tolerant (keep original proposal on LLM error).
4. Perform purely in-memory updates (no disk writes).
5. Preserve batch order and unaffected proposals.

---

## Systems Touched
- `src/core/propagate.py` (New module: functions for dependency search + LLM integration)
- `src/core/review.py` (Update S-5 state machine/actions to call propagation after edit)
- `tests/unit/test_s6_propagation.py` (Implementation of tests defined in contract)

---

## Assumptions
1. S-4 Batch output is structurally valid when it reaches S-6.
2. Edit events supply the new content verbatim inside the review loop.
3. The LLM might fail, time out, or produce malformed responses during re-evaluation. S-6 must gracefully fall back to the pre-propagation proposal.
4. Wikilink dependencies are defined strictly by exact titles enclosed in `[[ ]]` (e.g., `[[Attention Mechanism]]`), matched case-insensitively.

---

## Constraints (Restated)
- AD-2: No disk mutations—batch is held entirely in memory.
- AD-3: Sequential evaluation mapping strictly to downstream dependents.
- C-6: Dependency search bounded by Obsidian wikilinks format.
- L-8: No retry logic for LLM rate limits in MVP; failure to evaluate = use original and warn.
- ENGINEERING.md: Explicit input validation (`edited_title != ""`), deterministic dependency indexing, clear warning on fallback.

---

## Two Approaches Compared

### Approach A: Full Batch Graph Re-evaluation [REJECTED]
On edit, pass the entire remaining batch and the new upstream content to the LLM in a single prompt to reconstruct all dependent pages.

**Pros:**
- One LLM call.
- Might catch deeper contextual dependencies.

**Cons:** 
- Violates AD-3 (sequential per-page updates).
- High risk of unstructured mutations and context window limits.
- Untestable with strict boundary discipline (LLM dictates everything).

### Approach B: Linear Scan & Sequential Re-evaluations [PROPOSED CHOICE]
Use strict regex-based wikilink scanning to find indices of dependent proposals in the unreviewed `pending` batch. Loop sequentially over found dependents, calling `complete()` synchronously for each to individually update its content and conflicts.

**Pros:**
- Aligns directly with AD-3.
- Deterministic dependency mapping.
- Isolates LLM boundaries failure per-page.
- explicit handling, highly testable pure functions.

**Cons:** 
- Requires iterative calls, could hit rate limits if dependent count is very high (Acceptable per B-1/L-8 limits).

---

## Proposed Implementation Plan

1. **Create `src/core/propagate.py`:** Add `find_dependents` (regex scan) and `_re_evaluate_page` (LLM format prompt/re-parse conflict wrapper).
2. **Implement `propagate_edits` orchestration:** Loop over indices found, capturing `SystemExit` from individual LLM calls, and returning an updated cloned batch.
3. **Write Unit Tests (`test_s6_propagation.py`):** Fully mock LLM (`complete()`) and assert correct index finding, list order preservation, and graceful fallback on exceptions.
4. **Integrate backward into `src/core/review.py`:** When handling an `EDIT` event, trigger `propagate_edits` with the updated page and the remaining pending stack.
