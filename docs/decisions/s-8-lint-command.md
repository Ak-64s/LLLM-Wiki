# S-8 Lint Command — Pre-Implementation ADR

## Goal
Implement `python tools/lint.py [--save]` — five on-demand wiki health checks that scan all files in `vault/wiki/`, report issues grouped by check type to the terminal, and optionally write the same report to `vault/wiki/lint-report.md`.

The five checks:
1. **Orphan check** — pages with zero inbound `[[wikilinks]]` across the wiki
2. **Broken link check** — `[[Target]]` references where the target page does not exist
3. **Duplicate slug check** — two files that resolve to the same slug
4. **Empty page check** — pages with no meaningful content (whitespace-only or below a char threshold)
5. **Index staleness check** — `index.md` entries vs. actual files on disk (missing entries or stale entries pointing to deleted files)

Clean wiki produces "No issues found.". `--save` writes `vault/wiki/lint-report.md` with the same content.

## Systems Touched
- `tools/lint.py` — CLI entrypoint
- `src/core/lint.py` — lint engine with five check functions
- `src/core/config.py` — consumed for `vault_path` (read-only)
- `src/core/proposal.py` — reuse `slugify()` for duplicate slug detection consistency
- `tests/unit/test_s8_lint.py` — unit tests
- `contracts/s-8-lint-command.contract.md` — API structures
- `BACKLOG.md` — status tracking

Does NOT touch: `src/core/commit.py`, `src/core/batch.py`, `src/core/review.py`, or any LLM-related code. Lint is read-only against the vault.

## Assumptions
- Wiki pages live exclusively in `vault/wiki/{sources,entities,concepts}/`.
- `index.md` and `log.md` are bookkeeping files, excluded from orphan/empty/duplicate checks. (Updated: They are also excluded from supplying inbound links to regular pages in the orphan check).
- Wikilinks use Obsidian syntax `[[Page Name]]`. The regex `\[\[([^\]]+)\]\]` extracts targets.
- Link resolution maps `[[Page Name]]` to a file whose stem matches the slugified title, using `slugify()`.
- "Meaningful content" threshold: < 50 non-whitespace characters (excluding frontmatter) is flagged as empty.
- Lint is single-threaded and synchronous. Bound by ~300 pages, performance is not a concern.
- `lint-report.md` is overwritten on each `--save`, not appended.

## Constraints
- **C-1:** Python only.
- **C-5:** Wiki files are markdown only.
- **C-6:** Obsidian `[[wikilinks]]` syntax.
- **ENGINEERING:** validate inputs, fail clearly, no silent failures, observable output.
- No automated/schedule lint. On-demand only.

## Decision: Architecture Approach
Chosen **Approach A**: Core module `src/core/lint.py` + thin CLI in `tools/lint.py`.
- `src/core/lint.py` exposes check functions and `run_all_checks() -> LintReport`.
- `tools/lint.py` handles argparse, config, formatting, and disk write.
- Ensures maintainability and high testability for domain logic.

## Risks
- **Wikilink resolution ambiguity:** Hash collisions on identical slugs. Need resilient checking.
- **Index format coupling:** Staleness check parses `index.md`. Must share regex, not be brittle.
- **Bookkeeping file exclusion:** Must rigidly omit `index.md`, `log.md`, `overview.md`, `lint-report.md`.
- **sys.exit usage:** Only missing config/vault triggers exit. Failing lint checks are collected, not crashed.
