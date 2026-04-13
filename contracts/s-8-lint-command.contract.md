# Contract: S-8 Lint Command

| Field  | Value |
|--------|-------|
| Slice  | S-8 |
| Date   | 2026-04-12 |
| Status | DRAFT |
| Refs   | AD-7, C-1, C-5, C-6 |

---

## APIs

S-8 exposes Python module APIs (no HTTP server).
Primary module: `src.core.lint`.

### `run_all_checks(vault_path: str) -> LintReport`

| Aspect | Spec |
|--------|------|
| Module | `src.core.lint` |
| Input  | `vault_path` referencing the vault root. |
| Output | `LintReport` containing overall metrics and lists of `LintIssue` entries. |
| Raises | `SystemExit` if `vault_path` or required subdirectories do not exist. |
| Behavior | 1. Scans `vault/wiki/` ignoring `index.md`, `log.md`, `overview.md`, `lint-report.md`. <br> 2. Runs the 5 core checks synchronously. <br> 3. Aggregates results into a single reported structure. |
| Idempotent | Yes, read-only against the filesystem. |

### `format_report(report: LintReport) -> str`

| Aspect | Spec |
|--------|------|
| Module | `src.core.lint` |
| Input  | `LintReport` |
| Output | `str` formatted as a markdown console/file-friendly report. |

---

## HTTP Boundary

S-8 has no HTTP API and no outbound network calls.
HTTP status codes: **N/A**.

---

## Data Structures

### `LintIssue`

| Field | Type | Nullable | Constraints |
|-------|------|----------|-------------|
| `check_type` | `str` | NO | Strict enum: `orphan`, `broken_link`, `duplicate_slug`, `empty_page`, `stale_index`. |
| `file_path` | `str` | NO | Relative path to the vault, e.g., `sources/page.md` or `index.md`, or the expected target for `broken_link`. |
| `details` | `str` | NO | Human-readable explanation of the issue. |

### `LintReport`

| Field | Type | Nullable | Constraints |
|-------|------|----------|-------------|
| `total_issues` | `int` | NO | `>= 0`. |
| `issues` | `list[LintIssue]` | NO | Order is deterministic, usually grouped by `check_type` then `file_path`. |
| `duration_ms` | `int` | NO | `>= 0`. |

---

## Boundary Limits

| Boundary | Limit | Rationale |
|----------|-------|-----------|
| Empty page threshold | `< 50 chars` | Meaningful content requires at least 50 non-whitespace body characters. |
| Max pages in lint scan | memory bounded | Whole wiki is ~300 pages, safely handled in memory. |
| File read size ceiling | `<= 2,000,000` chars | From S-5/S-7 boundaries, prevents arbitrary pathological file read failures. |
| Tolerated time complexity | `O(N^2)` limits | With N ~ 300, cross-referencing links takes negligible time. |
| Expected latency | `< 1000 ms` | Synchronous filesystem scan shouldn't block usefully. |

---

## Tests

Execution method: `pytest tests/unit/test_s8_lint.py -v`

### Happy Path

| ID | Test | Input | Expected |
|----|------|-------|----------|
| T-8.01 | Clean wiki | properly cross-linked synthetic vault | `LintReport` returns 0 issues. Terminal states "No issues found." |
| T-8.02 | `--save` flag persistence | lint with `--save` | `vault/wiki/lint-report.md` equals terminal output precisely. |

### Edge Cases

| ID | Test | Input | Expected |
|----|------|-------|----------|
| T-8.03 | Exclusion list integrity | `index.md`, `log.md`, `lint-report.md` | These files are never flagged as orphans or empty pages. |
| T-8.04 | Content with frontmatter | page with long YAML frontmatter, empty body | Empty page check accurately isolates body char count. |

### Failure Cases

| ID | Test | Input | Expected |
|----|------|-------|----------|
| T-8.05 | Orphaned page detection | Page with 0 inbound wikilinks | 1 `orphan` issue for that page. |
| T-8.06 | Broken link detection | Page with `[[Nonexistent]]` | 1 `broken_link` issue citing source and target. |
| T-8.07 | Duplicate slug cross-category | `sources/foo.md`, `concepts/foo.md` | 2 `duplicate_slug` issues. |
| T-8.08 | Blank or whitespace user page | file with only spaces/newlines | 1 `empty_page` issue. |
| T-8.09 | Stale index detection | `index.md` missing entry or pointing to deleted file | 1 `stale_index` issue. |
| T-8.10 | Missing vault | execution with invalid `vault_path` | `SystemExit` cleanly exiting script, no traceback. |

---

## Execution Method

### Automated Tests
```bash
pytest tests/unit/test_s8_lint.py -v
```

### Manual Execution
```bash
python tools/lint.py
python tools/lint.py --save
```
