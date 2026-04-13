# ADR: Commit Layer Architecture (Pre-Implementation)

| Field   | Value |
|---------|-------|
| Slice   | S-7 |
| Date    | 2026-04-12 |
| Status  | PROPOSED (awaiting approval) |
| Decides | How approved proposals are atomically committed to vault storage |

---

## Re-read Project Files

Reviewed before planning:

- `PROJECT.md` (rev 9, S-7 started)
- `BACKLOG.md` (slice status/dependencies)
- `PROJECT_BRIEF.md` (done-when, anti-goals, constraints)
- `docs/architecture.md` (Commit Layer responsibilities and failure mode)
- `agents/skills/ENGINEERING.md` (boundary-first, explicit contracts)

---

## Goal (Restated)

Implement a deterministic commit layer that:

1. Persists approved `PageProposal` items to `vault/wiki/{category}/{slug}.md`.
2. Regenerates `vault/wiki/index.md` from the on-disk wiki state.
3. Appends a commit record to `vault/wiki/log.md`.
4. Guarantees AD-2 behavior: if any write fails, all writes from this commit are rolled back.

---

## Systems Touched

- New module: `src/core/commit.py` (commit orchestration, rollback, index/log updates)
- `src/core/proposal.py` (consume `PageProposal` shape from S-4/S-5)
- `src/core/config.py` (vault path consumption)
- `tools/ingest.py` (future integration point, not implemented in this slice planning doc)
- Tests: `tests/unit/test_s7_commit.py` (happy/edge/failure)
- Contract: `contracts/s-7-commit-layer.contract.md` (to be authored before implementation)

---

## Assumptions

1. Input proposals passed to commit are already validated by upstream slices (S-4/S-5).
2. Vault path is local filesystem, same filesystem for temp/staging and target writes.
3. Typical batch size remains near A-10 scale (roughly <= 15 proposals).
4. Process is single-user, single-writer for MVP (no concurrent writers to same vault).
5. `index.md` and `log.md` remain mechanical files (AD-11), so no manual approval loop.

---

## Constraints (Restated)

- AD-2: batch commit must be atomic from user perspective (no partial final state).
- AD-11: `index.md` and `log.md` are auto-committed.
- C-1: Python only.
- C-5/C-6: markdown page format and wikilink compatibility preserved.
- C-8: write only inside configured vault, never source directory.
- ENGINEERING: validate all boundaries, fail clearly, preserve observability context.

---

## Plan Implementation

1. Define S-7 contract first (`contracts/s-7-commit-layer.contract.md`):
   - API schemas
   - boundary limits
   - failure semantics
   - deterministic test matrix
2. Implement `src/core/commit.py` with explicit phases:
   - validate input proposals and destination paths
   - snapshot pre-commit state for touched files
   - write page files
   - regenerate `index.md`
   - append `log.md`
   - on any failure, rollback touched files from snapshot
3. Add deterministic unit tests:
   - happy path full commit
   - empty approved batch
   - mid-commit write failure with rollback verification
   - index regeneration correctness
   - log append format/content
   - path containment and invalid category/slug failures
4. Keep CLI wiring out of scope until contract/tests pass for core commit module.

---

## Two Approaches Compared

### Approach A: In-place write with per-file backup + rollback (PROPOSED)

How it works:

1. Capture pre-state for each touched file (existing bytes or non-existence marker).
2. Write pages/index/log directly to final paths.
3. If any step fails, restore all touched paths from captured pre-state.

Pros:

- Simple implementation with explicit rollback semantics.
- Easy to test deterministically in unit tests.
- Minimal extra directory choreography.

Cons:

- Requires careful rollback completeness discipline.
- Brief window where partial writes exist before rollback on failure.

### Approach B: Full staging directory then promote (ALTERNATIVE)

How it works:

1. Build entire target state in staging tree.
2. Promote staged files to final paths in a final step.

Pros:

- Cleaner separation between draft and committed states.
- Lower risk of partially-updated visible files during write phase.

Cons:

- Promotion across many files is not a single atomic operation.
- More complex mapping/cleanup logic for MVP.
- Higher I/O overhead and more moving parts.

Decision:

- Choose Approach A for MVP S-7, with strict rollback verification tests.
- Revisit staging-based optimization if operational failures show rollback fragility.

---

## Risks To Watch During Implementation

1. Rollback gaps if touched-file manifest is incomplete.
2. Path traversal risk if any file path is derived from untrusted fields.
3. Index regeneration drift if scan logic and write logic disagree.
4. Log append corruption under unexpected process termination.
5. Hidden coupling with future S-6 edit propagation semantics.

---

## Approval Gate

No S-7 implementation code should be written until this ADR is approved.
