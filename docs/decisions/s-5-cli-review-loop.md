# ADR: CLI Review Loop Architecture

| Field   | Value |
|---------|-------|
| Slice   | S-5 |
| Date    | 2026-04-12 |
| Status  | ACCEPTED |
| Decides | How interactive proposal review is structured before commit |

---

## Re-read Project Files

Reviewed before planning:

- `PROJECT.md` (rev 7, S-5 started)
- `PROJECT_BRIEF.md` (success criteria and anti-goals)
- `BACKLOG.md` (slice status/dependencies)
- `docs/architecture.md` (target flow and integration points)
- Existing ADR style in `docs/decisions/s-1...s-4`

---

## Goal (Restated)

Implement a deterministic, user-safe CLI review loop that:

1. Presents each `PageProposal` sequentially.
2. Supports accept/edit/reject.
3. Re-prompts rejected pages using user-provided reasons (AD-4).
4. Supports per-conflict resolution options (AD-8).
5. Produces an approved in-memory batch for S-6/S-7 without writing files.

---

## Systems Touched

- `tools/ingest.py` (entrypoint orchestration)
- `src/core/batch.py` (re-proposal integration and batch handoff)
- `src/core/proposal.py` (`PageProposal`/`Conflict` consumption)
- `src/core/llm.py` (reject -> re-propose boundary)
- New module: `src/core/review.py` (review state machine + action handlers)
- Tests: `tests/unit/test_s5_review.py`
- Contract: `contracts/s-5-cli-review-loop.contract.md` (to be added in implementation)

---

## Assumptions

1. `PageProposal` from S-4 is structurally valid on entry to S-5.
2. User is present interactively (anti-goal excludes unattended mode).
3. `$EDITOR` may be missing; fallback behavior must remain deterministic.
4. Reject reasons are short free text and may be low quality; loop still must remain stable.
5. Conflict entries are advisory and user decides outcome per conflict.
6. No disk writes happen in S-5 (AD-2 boundary discipline).

---

## Constraints (Restated)

- AD-2: Batch-then-commit; S-5 must not persist data.
- AD-3: Sequential behavior favored for predictability.
- AD-4: Reject means re-propose loop, not silent skip.
- AD-8: Per-conflict user-directed resolution.
- C-9: Use `$EDITOR`, fallback to `nano`.
- C-5/C-6: Markdown content and wikilink syntax preserved.
- ENGINEERING.md: explicit state transitions, no silent failures, observable boundary errors.

---

## Two Approaches Compared

### Approach A: Monolithic interactive loop in `tools/ingest.py` [REJECTED]

Keep all review logic in one imperative CLI function: rendering, editor opening, reject handling, conflict resolution, and approved-list assembly.

Pros:

- Fastest initial implementation.
- Minimal new modules.

Cons:

- Tight coupling between UI prompts and domain behavior.
- Hard to unit test without heavy input/output mocking.
- High regression risk as S-6 edit propagation is added.
- Violates ENGINEERING preference for explicit state ownership.

### Approach B: `ReviewEngine` state machine in `src/core/review.py` + thin CLI adapter [PROPOSED CHOICE]

Move domain behavior into a small state machine API; keep terminal prompt/rendering in `tools/ingest.py`.

Pros:

- Clear state transitions: pending -> edited -> accepted/rejected/abandoned.
- Easy deterministic tests over pure state actions.
- Lower coupling to terminal I/O and easier extension for S-6.
- Better failure boundaries and clearer observability hooks.

Cons:

- Slightly more upfront design work.
- Requires additional tests/contracts before shipping.

---

## Proposed Implementation Plan (Before Coding)

1. Define S-5 contract (`contracts/s-5-cli-review-loop.contract.md`) with action/result schemas and failure semantics.
2. Implement `src/core/review.py` with explicit transitions and validation.
3. Add editor integration helper (temp-file edit roundtrip + fallback path).
4. Add reject/re-propose boundary adapter from review engine -> S-4/S-3 orchestration.
5. Integrate CLI prompts in `tools/ingest.py` as thin orchestration only.
6. Add unit tests for:
   - accept/edit/reject/abandon flows
   - conflict decision paths
   - invalid input handling and deterministic re-prompting
7. Add integration smoke test path that returns approved batch without writes.

---

## Risks To Watch During Implementation

1. Infinite reject/re-propose loops without termination policy.
2. Editor failure paths (missing editor, non-zero exit, interrupted edits).
3. Hidden mutation of `PageProposal` objects across retries.
4. Prompt/response fragility in re-proposal path.

---

## Post-Implementation Update

### Implementation outcome

- `src/core/review.py` implemented with strict validation and explicit action transitions.
- `tests/unit/test_s5_review.py` added and passing (`23 passed`).
- Contract documented in `contracts/s-5-cli-review-loop.contract.md`.

### Assumptions check

| Assumption | Result | Notes |
|------------|--------|-------|
| `PageProposal` from S-4 is structurally valid on entry to S-5. | BROKEN | S-4 can output update entries without `existing_page`; S-5 correctly fails validation when `existing_path` is missing. |
| User-present interactive flow is acceptable for MVP. | HELD | Review loop remains interactive by design. |
| `$EDITOR` fallback path is deterministic. | HELD | Fallback implemented (`nano`), with explicit failure on editor launch/exit issues. |

### New rule added

S-4 must enforce `existing_page` for every `action="update"` plan entry before passing proposals to S-5.
