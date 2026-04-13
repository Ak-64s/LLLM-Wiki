# Contract: S-5 CLI Review Loop

| Field  | Value |
|--------|-------|
| Slice  | S-5 |
| Date   | 2026-04-12 |
| Status | DRAFT |
| Refs   | AD-2, AD-3, AD-4, AD-8, C-5, C-6, C-9, A-10 |

---

## APIs

S-5 exposes Python module APIs plus interactive CLI behavior. No HTTP server is exposed.
No new outbound HTTP boundary is introduced directly in S-5; re-proposal uses S-3 `complete()`.

### `review_batch(provider: str, config: Config, env: dict, proposals: list[PageProposal], source_text: str, source_meta: dict) -> list[PageProposal]`

| Aspect     | Spec |
|------------|------|
| Module     | `src.core.review` |
| Input      | `provider` -> `"gemini"` or `"lmstudio"`. `config` -> S-1 `Config`. `env` -> credentials dict. `proposals` -> ordered list from S-4. `source_text` -> original source content (non-empty). `source_meta` -> must include `"source"`. |
| Output     | `list[PageProposal]` -> approved proposals in review order, including user edits and conflict decisions. |
| Raises     | `SystemExit` on invalid batch shape, invalid proposal fields, editor execution failure, or unrecoverable re-proposal failure. |
| Behavior   | 1. Validate input batch via `validate_proposals()`. 2. Iterate proposals sequentially. 3. For each proposal, show diff/summary, then prompt action: `accept`, `edit`, `reject`, `abandon`. 4. `accept` -> add proposal to approved list. 5. `edit` -> open editor, replace proposal content with edited content, then keep page in current review step (user still chooses accept/reject/abandon). 6. `reject` -> require reject reason, call `repropose_page(...)`, replace current proposal with new version, then re-review same index (AD-4). 7. `abandon` -> drop proposal permanently. 8. For update proposals with conflicts, require per-conflict decision before final accept (`update_in_place` or `append_conflict_note`). 9. Return approved list. |
| Guarantee  | No disk writes in S-5 (AD-2). |
| Guarantee  | No proposal auto-accepted; every approved proposal passes explicit user action. |
| Idempotent | No (interactive, LLM re-proposal is non-deterministic). |

### `validate_proposals(proposals: list[PageProposal]) -> None`

| Aspect     | Spec |
|------------|------|
| Module     | `src.core.review` |
| Input      | `proposals` list from S-4. |
| Output     | None. |
| Raises     | `SystemExit` with actionable message naming invalid item and field. |
| Behavior   | Validates each proposal against strict schema (title, slug, category, content, action, conflicts, existing_path). Rejects null/empty/invalid enum values and invalid slug format. |
| Idempotent | Yes. Pure validation. |

### `normalize_action(raw: str) -> str`

| Aspect     | Spec |
|------------|------|
| Module     | `src.core.review` |
| Input      | Raw user action text. |
| Output     | Normalized action: one of `accept`, `edit`, `reject`, `abandon`. |
| Raises     | `ValueError` on invalid action token. |
| Behavior   | Trims whitespace, lowercases, supports aliases (`a`, `e`, `r`, `x`) mapped to canonical actions. |
| Idempotent | Yes. Pure function. |

### `edit_content(initial_content: str, editor_cmd: str | None = None) -> str`

| Aspect     | Spec |
|------------|------|
| Module     | `src.core.review` |
| Input      | `initial_content` markdown, non-empty. `editor_cmd` optional override. |
| Output     | Edited markdown content (non-empty after strip). |
| Raises     | `SystemExit` on editor launch failure, non-zero editor exit, or empty edited content. |
| Behavior   | 1. Resolve editor command: explicit `editor_cmd` -> `$EDITOR` -> `"nano"` fallback (C-9). 2. Write content to temp `.md` file. 3. Spawn editor blocking until exit. 4. Read edited text and validate non-empty. 5. Return edited text. |
| Side effects | Creates and deletes temporary file. |

### `collect_conflict_decisions(conflicts: list[Conflict]) -> list[ConflictDecision]`

| Aspect     | Spec |
|------------|------|
| Module     | `src.core.review` |
| Input      | `conflicts` from proposal. |
| Output     | `list[ConflictDecision]`, one decision per conflict in order. |
| Raises     | `SystemExit` on invalid or incomplete decision input. |
| Behavior   | For each conflict, prompt user for exactly one choice: `update_in_place` or `append_conflict_note`. Reprompt on invalid input. |
| Idempotent | No (interactive). |

### `repropose_page(provider: str, config: Config, env: dict, proposal: PageProposal, reject_reason: str, source_text: str, source_meta: dict) -> PageProposal`

| Aspect     | Spec |
|------------|------|
| Module     | `src.core.review` |
| Input      | Existing proposal, non-empty reject reason, source context. |
| Output     | New `PageProposal` replacing rejected version. |
| Raises     | `SystemExit` on invalid reject reason or re-proposal failure. |
| Behavior   | 1. Build re-proposal prompt with original proposal + reject reason. 2. Call S-3 `complete()`. 3. Parse returned markdown into updated proposal content (title/slug/category/action remain stable unless explicitly re-planned in prompt). 4. Return updated proposal for same review slot. |
| Boundary   | Uses S-3 LLM boundary; HTTP status handling is inherited from S-3 contract. |

---

## HTTP Boundary

S-5 has no direct HTTP API and no direct outbound HTTP calls.

HTTP status codes for re-proposal path are inherited from S-3:

| Provider | Status Codes |
|----------|--------------|
| Gemini   | 200, 400, 403, 429, 500, other non-200 |
| LM Studio| 200, non-200 |

On non-success statuses, S-3 raises `SystemExit`; S-5 propagates as re-proposal failure.

---

## Payload Schemas

### Review Action Payload (internal normalized)

```json
{
  "action": "accept | edit | reject | abandon",
  "reject_reason": "string (required when action=reject, otherwise omitted)"
}
```

Validation:

- `action` required, closed enum.
- `reject_reason` required for `reject`, forbidden otherwise.
- `reject_reason` length: 5..1000 chars after trim.

### Conflict Decision Payload

```json
{
  "existing_page": "string",
  "description": "string",
  "decision": "update_in_place | append_conflict_note"
}
```

Validation:

- One payload per input conflict.
- `existing_page` and `description` must match source conflict.
- `decision` required, closed enum.

### Re-proposal Request Payload (internal prompt input)

```json
{
  "title": "string",
  "category": "sources | entities | concepts",
  "action": "create | update",
  "original_content": "string",
  "reject_reason": "string",
  "source_text": "string",
  "source_ref": "string"
}
```

Validation:

- All fields required.
- `original_content` and `source_text` non-empty.
- `reject_reason` length 5..1000.

---

## Data Structures

### `PageProposal` (input/output; from S-4, revalidated in S-5)

| Field           | Type            | Nullable | Constraints |
|-----------------|-----------------|----------|-------------|
| `title`         | `str`           | NO       | 1..200 chars after trim. |
| `slug`          | `str`           | NO       | 1..220 chars, regex `^[a-z0-9]+(?:-[a-z0-9]+)*$`. |
| `category`      | `str`           | NO       | `sources` or `entities` or `concepts`. |
| `content`       | `str`           | NO       | 1..2,000,000 chars after trim. Markdown only (C-5). |
| `action`        | `str`           | NO       | `create` or `update`. |
| `conflicts`     | `list[Conflict]`| NO       | May be empty. |
| `existing_path` | `str`           | NO       | Required non-empty when `action=update`; must be empty when `action=create`. Max 260 chars. |

### `Conflict` (input from S-4)

| Field           | Type  | Nullable | Constraints |
|-----------------|-------|----------|-------------|
| `existing_page` | `str` | NO       | 1..260 chars. |
| `description`   | `str` | NO       | 1..2000 chars after trim. |
| `source_ref`    | `str` | NO       | 1..2048 chars. |

### `ConflictDecision` (new in S-5)

| Field           | Type  | Nullable | Constraints |
|-----------------|-------|----------|-------------|
| `existing_page` | `str` | NO       | Mirrors source `Conflict.existing_page`. |
| `description`   | `str` | NO       | Mirrors source `Conflict.description`. |
| `decision`      | `str` | NO       | `update_in_place` or `append_conflict_note`. |

### `ReviewResult` (internal aggregation)

| Field              | Type                  | Nullable | Constraints |
|--------------------|-----------------------|----------|-------------|
| `approved`         | `list[PageProposal]`  | NO       | Ordered by acceptance time. |
| `abandoned_titles` | `list[str]`           | NO       | Titles explicitly abandoned. |
| `events`           | `list[ReviewEvent]`   | NO       | One event per terminal action. |

### `ReviewEvent`

| Field            | Type   | Nullable | Constraints |
|------------------|--------|----------|-------------|
| `page_index`     | `int`  | NO       | `>= 0`. |
| `title`          | `str`  | NO       | 1..200 chars. |
| `action`         | `str`  | NO       | `accept` or `edit` or `reject` or `abandon`. |
| `edited`         | `bool` | NO       | True if content changed in editor. |
| `reject_reason`  | `str`  | YES      | Present only for `reject`. |

---

## Boundary Limits

| Boundary | Limit | Rationale |
|----------|-------|-----------|
| Proposals per batch | 0..50 | A-10 expects ~15; 50 is hard safety cap for interactive usability. |
| Proposal content size | <= 2,000,000 chars | Prevent runaway memory/editor behavior in CLI workflow. |
| Reject reason length | 5..1000 chars | Too-short reasons are low signal; too-long reasons are prompt noise. |
| Invalid action retries per prompt | 20 max | Prevent infinite loops on malformed input streams. |
| Invalid conflict-choice retries per conflict | 20 max | Same as above. |
| Editor process runtime | No hard timeout (interactive) | User may take arbitrary time; explicit user-in-the-loop design. |
| Re-proposal attempts per page | 10 max | Prevent unbounded reject/re-propose loops; user must abandon after cap. |
| Path lengths (`existing_path`, `existing_page`) | <= 260 chars | Windows path safety and parity with S-1 constraints. |

Rate limits:

- None introduced by S-5 itself.
- Re-proposal invokes S-3 and inherits provider rate limits (Gemini free-tier, LM Studio local capacity).

Expected latency:

- Non-LLM review operations: <= 100 ms per action (excluding editor time).
- Re-proposal latency: inherited from S-3 (Gemini up to ~120s read timeout, LM Studio up to ~300s).

---

## Tests

Execution method: `pytest tests/unit/test_s5_review.py -v`

Dependencies: `pytest`. Editor subprocess, input, output, and S-3 `complete()` calls must be mocked.
Tests must be deterministic and run offline.

### Happy Path

| ID     | Test | Input | Expected |
|--------|------|-------|----------|
| T-5.01 | Accept single proposal | One valid create proposal, action `accept` | Returns list of length 1 with unchanged proposal. |
| T-5.02 | Accept multiple proposals in order | Three proposals, all `accept` | Returns three approved proposals preserving review order. |
| T-5.03 | Edit then accept | Valid proposal, action `edit` with non-empty modified content then `accept` | Returned proposal content equals edited content. |
| T-5.04 | Reject then accept re-proposal | Action `reject` with reason, mocked `repropose_page` returns replacement, then `accept` | Returned list contains replacement proposal. |
| T-5.05 | Conflict decisions captured | Update proposal with 2 conflicts, valid decisions provided | Proposal accepted with 2 conflict decisions recorded. |
| T-5.06 | Abandon proposal | Action `abandon` | Proposal omitted from approved list. |

### Edge Cases

| ID     | Test | Input | Expected |
|--------|------|-------|----------|
| T-5.07 | Empty batch | `proposals=[]` | Returns `[]` cleanly. |
| T-5.08 | Action aliases accepted | Inputs `a`, `e`, `r`, `x` | Normalize to canonical actions. |
| T-5.09 | Whitespace/case action normalization | `"  AcCePt  "` | Normalizes to `accept`. |
| T-5.10 | Missing `$EDITOR` uses fallback | No `editor_cmd`, no env var | Uses `"nano"` fallback path. |
| T-5.11 | Update proposal with no conflicts | `action=update`, empty conflicts | Accept path does not prompt conflict choices. |
| T-5.12 | Reject reason at min length | 5 chars | Accepted. |
| T-5.13 | Reject reason at max length | 1000 chars | Accepted. |
| T-5.14 | Large but valid content | Content near 2,000,000 chars | Passes validation and review path. |
| T-5.15 | Max re-proposal attempts boundary | 10 rejects with valid reason then accept | Works until cap, then accepts. |

### Failure Cases

| ID     | Test | Input | Expected |
|--------|------|-------|----------|
| T-5.16 | Invalid proposal category | `category="other"` | `SystemExit` naming field/category. |
| T-5.17 | Invalid slug format | slug with uppercase/space | `SystemExit` naming slug regex failure. |
| T-5.18 | Empty proposal content | whitespace-only content | `SystemExit` naming content validation failure. |
| T-5.19 | Update with empty `existing_path` | `action=update`, `existing_path=""` | `SystemExit` naming cross-field violation. |
| T-5.20 | Create with non-empty `existing_path` | `action=create`, `existing_path` set | `SystemExit` naming cross-field violation. |
| T-5.21 | Invalid action token | user input `"shipit"` | Reprompt; after retry cap -> `SystemExit`. |
| T-5.22 | Reject without reason | action `reject`, reason empty | Reprompt; after retry cap -> `SystemExit`. |
| T-5.23 | Reject reason too short | reason length < 5 | Reprompt; no re-proposal call until valid. |
| T-5.24 | Reject reason too long | reason length > 1000 | Reprompt; no re-proposal call until valid. |
| T-5.25 | Editor returns non-zero exit | mocked subprocess exit code 1 | `SystemExit` naming editor failure. |
| T-5.26 | Editor output empty | edited file whitespace-only | `SystemExit` naming empty edit result. |
| T-5.27 | Re-proposal failure | mocked S-3 `complete()` raises `SystemExit` | `SystemExit` propagated with context. |
| T-5.28 | Invalid conflict decision | decision not in enum | Reprompt; after retry cap -> `SystemExit`. |
| T-5.29 | Mismatched conflict decision count | fewer decisions than conflicts | `SystemExit` naming mismatch. |
| T-5.30 | Batch size over cap | 51 proposals | `SystemExit` naming boundary limit. |

---

## Execution Method

### Unit Tests

```bash
pip install -r requirements.txt
pip install pytest
pytest tests/unit/test_s5_review.py -v
```

Testing rules:

- Mock interactive input using `patch("builtins.input", ...)`.
- Mock editor subprocess with `patch("subprocess.run", ...)`.
- Mock re-proposal LLM boundary with `patch("src.core.review.complete", ...)`.
- Use deterministic proposal fixtures from `PageProposal` dataclass.

### Manual Smoke Test

```bash
# 1) Run ingest with a small text source (after S-5 implementation)
python tools/ingest.py sources/notes/example.md

# 2) For each proposal:
#    - choose edit, modify content, then accept
#    - choose reject and provide reason, verify re-proposal appears
#    - choose abandon for one proposal

# 3) Verify:
#    - approved proposal count matches explicit accepts only
#    - no files are written during S-5 (commit is S-7 responsibility)
```

---

## ENGINEERING.md Validation Checklist

| Principle | Satisfied? |
|-----------|------------|
| Explicit > implicit | Review actions and conflict choices are closed enums with strict schemas. |
| Simple > clever | Single review engine API, thin CLI adapter, deterministic transitions. |
| Contracts define behavior | This document defines API behavior, payload schemas, limits, and tests. |
| Systems fail at boundaries | Editor, user input, and re-proposal boundaries have explicit failure semantics. |
| Validate all inputs | Proposal fields, actions, reasons, and conflict decisions are strictly validated. |
| Fail fast and clearly | Validation and boundary failures return actionable `SystemExit` messages. |
| Never swallow errors | Re-proposal/editor failures are surfaced, not ignored. |
| Observability | Review events and decisions are structured for logging hooks. |

