# Contract: S-7 Commit Layer

| Field  | Value |
|--------|-------|
| Slice  | S-7 |
| Date   | 2026-04-12 |
| Status | DRAFT |
| Refs   | AD-2, AD-7, AD-11, C-1, C-5, C-6, C-8, A-10 |

---

## APIs

S-7 exposes Python module APIs (no HTTP server).  
No new outbound HTTP boundary is introduced in S-7.

Primary module: `src.core.commit`.

### `commit_approved_batch(config: Config, approved: list[PageProposal], source_meta: dict, run_id: str | None = None, committed_at: str | None = None) -> CommitResult`

| Aspect | Spec |
|--------|------|
| Module | `src.core.commit` |
| Input | `config` from S-1. `approved` list from S-5/S-6. `source_meta` must include `"source"`. Optional `run_id` (trace ID) and `committed_at` (UTC timestamp override). |
| Output | `CommitResult` with commit id, touched paths, page counts, and rollback status. |
| Raises | `SystemExit` on invalid payload/path/category/slug/content, path containment violation, duplicate targets, write failure, rollback failure. |
| Behavior | 1. Validate request strictly. 2. Resolve and validate target paths under `{vault}/wiki/{category}/{slug}.md`. 3. Snapshot pre-state for all touched files (`pages + index.md + log.md`). 4. Write page files. 5. Regenerate `index.md`. 6. Append commit line to `log.md`. 7. On any failure, rollback all touched files to pre-state, then raise `SystemExit` with context. 8. On success, return `CommitResult`. |
| Guarantee | Atomic from user perspective (AD-2): either all page/index/log changes are committed, or pre-commit state is restored. |
| Side effects | Filesystem writes inside vault only. No network calls. |
| Idempotent | No. Re-running can append additional log entries and update timestamps. |

### `validate_commit_payload(approved: list[PageProposal], source_meta: dict, run_id: str | None = None) -> None`

| Aspect | Spec |
|--------|------|
| Module | `src.core.commit` |
| Input | `approved` and `source_meta` from caller. |
| Output | None. |
| Raises | `SystemExit` naming the invalid field and index. |
| Behavior | Strictly validates shape, enum values, lengths, duplicate target paths, and `source_meta["source"]` presence/type/length. |
| Idempotent | Yes. Pure validation. |

### `regenerate_index(vault_path: str) -> str`

| Aspect | Spec |
|--------|------|
| Module | `src.core.commit` |
| Input | Vault root path. |
| Output | Full markdown content for `vault/wiki/index.md`. |
| Raises | `SystemExit` on unreadable wiki directory or invalid on-disk page set. |
| Behavior | Scans `wiki/sources`, `wiki/entities`, `wiki/concepts`; builds deterministic index content from current disk state. |
| Idempotent | Yes for unchanged filesystem state. |

### `build_log_entry(commit_id: str, source_ref: str, pages_created: int, pages_updated: int, committed_at: str, run_id: str | None = None) -> str`

| Aspect | Spec |
|--------|------|
| Module | `src.core.commit` |
| Input | Commit metadata fields. |
| Output | Single markdown line appended to `log.md`. |
| Raises | `SystemExit` on invalid field lengths/format. |
| Behavior | Produces compact deterministic line including timestamp, source, counts, and commit id. |
| Idempotent | Yes for identical input. |

---

## HTTP Boundary

S-7 has no direct HTTP API and no outbound HTTP calls.

HTTP status codes: **N/A**.  
Any HTTP-related failures in upstream/downstream slices are outside S-7 scope.

---

## Payload Schemas

### Commit Request (internal API payload)

```json
{
  "approved": [
    {
      "title": "string",
      "slug": "string",
      "category": "sources | entities | concepts",
      "content": "string",
      "action": "create | update",
      "conflicts": [],
      "existing_path": "string"
    }
  ],
  "source_meta": {
    "source": "string"
  },
  "run_id": "string | null",
  "committed_at": "YYYY-MM-DDTHH:MM:SSZ | null"
}
```

Validation:

- `approved` required, list type, max 50 items.
- `source_meta` required, dict type, key `"source"` required.
- `run_id` optional; when present: 1..64 chars, `[A-Za-z0-9._:-]+`.
- `committed_at` optional; when present: strict UTC ISO8601 `YYYY-MM-DDTHH:MM:SSZ`.

### Commit Result (internal API response)

```json
{
  "commit_id": "string",
  "vault_path": "string",
  "page_count": 0,
  "created_count": 0,
  "updated_count": 0,
  "written_paths": ["string"],
  "index_path": "string",
  "log_path": "string",
  "rolled_back": false,
  "duration_ms": 0
}
```

Validation:

- `commit_id` required, 8..64 chars.
- `page_count == created_count + updated_count`.
- `written_paths` required, each path inside vault and <= 260 chars relative component length.
- `rolled_back` indicates rollback attempted and completed.

---

## Data Structures

### `PageProposal` consumed by S-7 (strict re-validation)

| Field | Type | Nullable | Constraints |
|-------|------|----------|-------------|
| `title` | `str` | NO | 1..200 chars after trim. |
| `slug` | `str` | NO | 1..220 chars, regex `^[a-z0-9]+(?:-[a-z0-9]+)*$`. |
| `category` | `str` | NO | `sources` or `entities` or `concepts`. |
| `content` | `str` | NO | 1..2,000,000 chars after trim. |
| `action` | `str` | NO | `create` or `update`. |
| `conflicts` | `list[Conflict]` | NO | List type required; content ignored by commit logic. |
| `existing_path` | `str` | NO | For `update`: 1..260 chars. For `create`: empty string. |

### `CommitResult` (new dataclass in S-7)

| Field | Type | Nullable | Constraints |
|-------|------|----------|-------------|
| `commit_id` | `str` | NO | 8..64 chars (hex/uuid-safe token). |
| `vault_path` | `str` | NO | Absolute or config path string; non-empty. |
| `page_count` | `int` | NO | 0..50 |
| `created_count` | `int` | NO | 0..50 |
| `updated_count` | `int` | NO | 0..50 |
| `written_paths` | `list[str]` | NO | Each path must resolve inside vault. |
| `index_path` | `str` | NO | Must be `vault/wiki/index.md`. |
| `log_path` | `str` | NO | Must be `vault/wiki/log.md`. |
| `rolled_back` | `bool` | NO | True only on failed commit with successful restoration. |
| `duration_ms` | `int` | NO | `>= 0`. |

### `PreStateSnapshot` (internal)

| Field | Type | Nullable | Constraints |
|-------|------|----------|-------------|
| `path` | `str` | NO | Resolved path inside vault. |
| `existed` | `bool` | NO | Indicates pre-commit existence. |
| `bytes_before` | `bytes` | YES | Required when `existed=true`; null when `existed=false`. |

### `source_meta` minimum schema consumed by S-7

| Field | Type | Nullable | Constraints |
|-------|------|----------|-------------|
| `source` | `str` | NO | 1..2048 chars after trim. |

---

## Boundary Limits

| Boundary | Limit | Rationale |
|----------|-------|-----------|
| Approved proposals per commit | 0..50 | Align with S-5 upper cap. |
| Single page content size | <= 2,000,000 chars | Align with S-5 content boundary. |
| Aggregate commit content size | <= 20,000,000 chars | Prevent pathological memory spikes during snapshot/write. |
| `source_meta.source` length | 1..2048 chars | Stable log/index metadata boundary. |
| `run_id` length | 1..64 chars (optional) | Traceability without oversized log fields. |
| Relative path component length | <= 260 chars | Windows-safe path budget parity with prior slices. |
| Commit ID length | 8..64 chars | Compact but unique enough for logs/debugging. |
| Rollback scope | all touched files only | Explicit blast radius and deterministic recovery. |
| File write retries | 0 (fail-fast) | Simpler deterministic atomic semantics in MVP. |

Rate limits:

- None (filesystem-only slice).

Expected latency (local SSD, <=15 pages):

- Typical: <= 500 ms.
- P95: <= 2000 ms.
- Large content or slow disks may exceed; still bounded by local I/O behavior.

---

## Tests

Execution method: `pytest tests/unit/test_s7_commit.py -v`

Dependencies: `pytest`.  
Use temp directories (`tmp_path`) and filesystem mocking for failure injection.

### Happy Path

| ID | Test | Input | Expected |
|----|------|-------|----------|
| T-7.01 | Commit create-only batch | 3 create proposals | 3 files written + index/log updated, `rolled_back=false`. |
| T-7.02 | Commit mixed create/update | create + update proposals | Correct counts in `CommitResult`; both file types persisted. |
| T-7.03 | Deterministic index regeneration | stable on-disk pages | Same index output for repeated calls. |
| T-7.04 | Log entry append | valid metadata | one new log line with commit id/source/counts. |
| T-7.05 | Empty approved batch | `approved=[]` | No page writes; index/log policy behaves per contract (no-op or minimal log) deterministically. |
| T-7.06 | Paths returned in result | valid commit | `written_paths`, `index_path`, `log_path` accurate and inside vault. |

### Edge Cases

| ID | Test | Input | Expected |
|----|------|-------|----------|
| T-7.07 | Max batch size | 50 proposals | Valid commit path without validation failure. |
| T-7.08 | Max content size boundary | content length exactly 2,000,000 | Accepted. |
| T-7.09 | Existing file update | update target already exists | File replaced; snapshot stores prior bytes. |
| T-7.10 | New category directories missing | empty vault/wiki subdirs absent | Commit creates required dirs before writes. |
| T-7.11 | run_id provided | valid 64-char run_id | Propagates into log entry/output context. |
| T-7.12 | committed_at override | valid UTC timestamp | Used in log entry deterministically. |
| T-7.13 | Non-ASCII markdown content | multilingual content | persisted unchanged (UTF-8). |
| T-7.14 | Duplicate slugs across different categories | `sources/foo`, `concepts/foo` | Both valid; distinct paths. |

### Failure Cases

| ID | Test | Input | Expected |
|----|------|-------|----------|
| T-7.15 | Invalid category | proposal category not enum | `SystemExit` naming field/index. |
| T-7.16 | Invalid slug regex | slug contains space/uppercase/path chars | `SystemExit`. |
| T-7.17 | Empty content | whitespace-only content | `SystemExit`. |
| T-7.18 | Update missing existing_path | update with empty path | `SystemExit`. |
| T-7.19 | Create with non-empty existing_path | create with path set | `SystemExit`. |
| T-7.20 | Duplicate target paths in batch | two proposals resolve same final path | `SystemExit`. |
| T-7.21 | Path traversal attempt via slug | malicious slug/path injection | `SystemExit` containment violation. |
| T-7.22 | Invalid source_meta type | source_meta not dict | `SystemExit`. |
| T-7.23 | Missing source_meta.source | source key absent | `SystemExit`. |
| T-7.24 | Invalid committed_at format | non-UTC timestamp string | `SystemExit`. |
| T-7.25 | Mid-page write failure triggers rollback | injected failure on Nth write | all touched files restored; `SystemExit` with rollback context. |
| T-7.26 | index write failure triggers rollback | injected failure writing index | pages restored to pre-state; no partial commit left. |
| T-7.27 | log write failure triggers rollback | injected failure appending log | pages/index restored to pre-state. |
| T-7.28 | rollback failure surfaced | failure while restoring snapshot | `SystemExit` includes rollback-failure context. |
| T-7.29 | Oversized aggregate payload | >20,000,000 chars | `SystemExit` boundary-limit failure. |
| T-7.30 | Invalid run_id format | disallowed chars/too long | `SystemExit`. |

---

## Execution Method

### Unit Tests

```bash
pip install -r requirements.txt
pip install pytest
pytest tests/unit/test_s7_commit.py -v
```

Testing rules:

- Use `tmp_path` for real filesystem verification.
- Mock failure points for write and rollback branches (e.g., patched `Path.write_text`, `Path.open`).
- Assert both file contents and absence of partial state after failure.
- Keep tests deterministic and offline.

### Manual Smoke Test

```bash
# After S-7 implementation:
python -c "
from src.core.config import load_config
from src.core.commit import commit_approved_batch
from src.core.proposal import PageProposal

cfg = load_config()
approved = [
    PageProposal(
        title='Test Commit Page',
        slug='test-commit-page',
        category='concepts',
        content='Commit layer smoke test.',
        action='create',
        conflicts=[],
        existing_path='',
    )
]
result = commit_approved_batch(cfg, approved, {'source': 'manual-smoke'})
print(result.commit_id, result.page_count, result.rolled_back)
"
```

Expected:

- page file created under `vault/wiki/concepts/`
- `index.md` regenerated
- `log.md` appended
- `rolled_back=False`

---

## ENGINEERING.md Validation Checklist

| Principle | Satisfied? |
|-----------|------------|
| Explicit > implicit | Commit phases and rollback semantics are explicit. |
| Contracts define behavior | API schemas, boundaries, and failure semantics are specified. |
| Systems fail at boundaries | Validation, path containment, write failures, and rollback failures are explicit test targets. |
| Validate all inputs | Strict field/type/length/enum checks on all commit inputs. |
| Fail fast and clearly | `SystemExit` messages must identify field/path/stage. |
| Never swallow errors | Write and rollback failures are surfaced with context. |
| Observability | `commit_id`, optional `run_id`, and result metadata support traceability. |
