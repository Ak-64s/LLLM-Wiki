"""Commit layer. Contract: contracts/s-7-commit-layer.contract.md"""

import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.core.proposal import PageProposal

_VALID_CATEGORIES = ("sources", "entities", "concepts")
_VALID_ACTIONS = ("create", "update")
_SLUG_REGEX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_RUN_ID_REGEX = re.compile(r"^[A-Za-z0-9._:\-]+$")
_COMMITTED_AT_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_MAX_BATCH_SIZE = 50
_MAX_CONTENT_SIZE = 2_000_000
_MAX_AGGREGATE_SIZE = 20_000_000
_MAX_SOURCE_LEN = 2048
_MAX_RUN_ID_LEN = 64
_MAX_TITLE_LEN = 200
_MAX_SLUG_LEN = 220
_MAX_PATH_LEN = 260


@dataclass
class CommitResult:
    commit_id: str
    vault_path: str
    page_count: int
    created_count: int
    updated_count: int
    written_paths: list[str]
    index_path: str
    log_path: str
    rolled_back: bool
    duration_ms: int


@dataclass
class _PreStateSnapshot:
    path: str
    existed: bool
    bytes_before: bytes | None


def _fail(msg: str) -> None:
    sys.exit(msg)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_commit_payload(
    approved: list[PageProposal],
    source_meta: dict,
    run_id: str | None = None,
) -> None:
    if not isinstance(approved, list):
        _fail("approved must be a list.")
    if len(approved) > _MAX_BATCH_SIZE:
        _fail(f"approved contains {len(approved)} items, maximum is {_MAX_BATCH_SIZE}.")

    if not isinstance(source_meta, dict):
        _fail("source_meta must be a dict.")
    source = source_meta.get("source")
    if not source or not isinstance(source, str):
        _fail("source_meta must contain key 'source' (non-empty string).")
    if not source.strip():
        _fail("source_meta['source'] is empty after trim.")
    if len(source.strip()) > _MAX_SOURCE_LEN:
        _fail(f"source_meta['source'] exceeds {_MAX_SOURCE_LEN} chars.")

    if run_id is not None:
        if not isinstance(run_id, str) or not run_id:
            _fail("run_id must be a non-empty string when provided.")
        if len(run_id) > _MAX_RUN_ID_LEN:
            _fail(f"run_id exceeds {_MAX_RUN_ID_LEN} chars.")
        if not _RUN_ID_REGEX.match(run_id):
            _fail("run_id contains invalid characters. Allowed: [A-Za-z0-9._:-].")

    target_paths: set[str] = set()
    aggregate_size = 0

    for i, p in enumerate(approved):
        title = p.title.strip() if p.title else ""
        if not title:
            _fail(f"approved[{i}].title is empty.")
        if len(title) > _MAX_TITLE_LEN:
            _fail(f"approved[{i}].title exceeds {_MAX_TITLE_LEN} chars.")

        if not p.slug:
            _fail(f"approved[{i}].slug is empty.")
        if len(p.slug) > _MAX_SLUG_LEN:
            _fail(f"approved[{i}].slug exceeds {_MAX_SLUG_LEN} chars.")
        if not _SLUG_REGEX.match(p.slug):
            _fail(
                f"approved[{i}].slug is invalid: '{p.slug}'. "
                f"Must match ^[a-z0-9]+(?:-[a-z0-9]+)*$."
            )

        if p.category not in _VALID_CATEGORIES:
            _fail(
                f"approved[{i}].category is invalid: '{p.category}'. "
                f"Must be one of: {', '.join(_VALID_CATEGORIES)}."
            )

        content = p.content.strip() if p.content else ""
        if not content:
            _fail(f"approved[{i}].content is empty after trim.")
        if len(content) > _MAX_CONTENT_SIZE:
            _fail(f"approved[{i}].content exceeds {_MAX_CONTENT_SIZE} chars.")
        aggregate_size += len(content)

        if p.action not in _VALID_ACTIONS:
            _fail(
                f"approved[{i}].action is invalid: '{p.action}'. "
                f"Must be one of: {', '.join(_VALID_ACTIONS)}."
            )

        if not isinstance(p.conflicts, list):
            _fail(f"approved[{i}].conflicts must be a list.")

        if p.action == "update":
            if not p.existing_path or not p.existing_path.strip():
                _fail(f"approved[{i}].existing_path is required for 'update' action.")
            if len(p.existing_path) > _MAX_PATH_LEN:
                _fail(f"approved[{i}].existing_path exceeds {_MAX_PATH_LEN} chars.")
        elif p.action == "create":
            if p.existing_path:
                _fail(f"approved[{i}].existing_path must be empty for 'create' action.")

        target = f"{p.category}/{p.slug}.md"
        if target in target_paths:
            _fail(f"Duplicate target path: {target} (approved[{i}]).")
        target_paths.add(target)

    if aggregate_size > _MAX_AGGREGATE_SIZE:
        _fail(
            f"Aggregate content size ({aggregate_size}) exceeds "
            f"{_MAX_AGGREGATE_SIZE} chars."
        )


# ---------------------------------------------------------------------------
# Index generation
# ---------------------------------------------------------------------------

def regenerate_index(vault_path: str) -> str:
    wiki = Path(vault_path) / "wiki"
    if not wiki.is_dir():
        _fail(f"Wiki directory not found: {wiki}")

    lines: list[str] = ["# Wiki Index", ""]

    for category in _VALID_CATEGORIES:
        cat_dir = wiki / category
        lines.append(f"## {category.capitalize()}")
        lines.append("")
        if cat_dir.is_dir():
            entries = sorted(f.stem for f in cat_dir.iterdir() if f.suffix == ".md")
            for stem in entries:
                lines.append(f"- [[{stem}]] — `{category}/{stem}.md`")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Log entry
# ---------------------------------------------------------------------------

def build_log_entry(
    commit_id: str,
    source_ref: str,
    pages_created: int,
    pages_updated: int,
    committed_at: str,
    run_id: str | None = None,
) -> str:
    if not commit_id or len(commit_id) < 8 or len(commit_id) > 64:
        _fail("commit_id must be 8..64 chars.")
    if not source_ref:
        _fail("source_ref is empty.")
    if not committed_at or not _COMMITTED_AT_REGEX.match(committed_at):
        _fail(f"committed_at format invalid: '{committed_at}'.")

    parts = [
        f"[{committed_at}]",
        f"source={source_ref}",
        f"created={pages_created}",
        f"updated={pages_updated}",
        f"commit={commit_id}",
    ]
    if run_id:
        parts.append(f"run={run_id}")

    return "- " + " | ".join(parts)


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def _rollback(snapshots: list[_PreStateSnapshot]) -> list[str]:
    errors: list[str] = []
    for snap in snapshots:
        p = Path(snap.path)
        try:
            if snap.existed:
                p.write_bytes(snap.bytes_before)
            else:
                if p.exists():
                    p.unlink()
        except Exception as e:
            errors.append(f"{snap.path}: {e}")
    return errors


# ---------------------------------------------------------------------------
# Commit orchestrator
# ---------------------------------------------------------------------------

def commit_approved_batch(
    config,
    approved: list[PageProposal],
    source_meta: dict,
    run_id: str | None = None,
    committed_at: str | None = None,
) -> CommitResult:
    start = time.monotonic()

    if committed_at is not None:
        if not _COMMITTED_AT_REGEX.match(committed_at):
            _fail(f"committed_at format invalid: '{committed_at}'.")

    validate_commit_payload(approved, source_meta, run_id)

    vault_path = config.vault_path
    wiki_path = Path(vault_path) / "wiki"
    commit_id = uuid.uuid4().hex[:16]
    ts = committed_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    index_path = wiki_path / "index.md"
    log_path = wiki_path / "log.md"

    if not approved:
        elapsed = int((time.monotonic() - start) * 1000)
        return CommitResult(
            commit_id=commit_id,
            vault_path=vault_path,
            page_count=0,
            created_count=0,
            updated_count=0,
            written_paths=[],
            index_path=str(index_path),
            log_path=str(log_path),
            rolled_back=False,
            duration_ms=elapsed,
        )

    vault_resolved = Path(vault_path).resolve()
    targets: list[tuple[PageProposal, Path]] = []
    for i, p in enumerate(approved):
        target = wiki_path / p.category / f"{p.slug}.md"
        try:
            target.resolve().relative_to(vault_resolved)
        except ValueError:
            _fail(f"Path containment violation: approved[{i}] resolves outside vault.")
        targets.append((p, target))

    created_count = sum(1 for p in approved if p.action == "create")
    updated_count = sum(1 for p in approved if p.action == "update")
    source_ref = source_meta.get("source", "")
    log_line = build_log_entry(commit_id, source_ref, created_count, updated_count, ts, run_id)

    snapshots: list[_PreStateSnapshot] = []
    all_touchable = [t for _, t in targets] + [index_path, log_path]
    for p in all_touchable:
        if p.exists():
            snapshots.append(_PreStateSnapshot(
                path=str(p), existed=True, bytes_before=p.read_bytes(),
            ))
        else:
            snapshots.append(_PreStateSnapshot(
                path=str(p), existed=False, bytes_before=None,
            ))

    written_paths: list[str] = []

    try:
        for cat in _VALID_CATEGORIES:
            (wiki_path / cat).mkdir(parents=True, exist_ok=True)

        for proposal, target in targets:
            target.write_text(proposal.content, encoding="utf-8")
            written_paths.append(str(target))

        index_content = regenerate_index(vault_path)
        index_path.write_text(index_content, encoding="utf-8")

        existing_log = ""
        if log_path.exists():
            existing_log = log_path.read_text(encoding="utf-8")
        new_log = existing_log
        if new_log and not new_log.endswith("\n"):
            new_log += "\n"
        new_log += log_line + "\n"
        log_path.write_text(new_log, encoding="utf-8")

    except Exception as e:
        rollback_errors = _rollback(snapshots)
        if rollback_errors:
            _fail(
                f"Commit failed: {e}. CRITICAL: Rollback also failed: "
                f"{'; '.join(rollback_errors)}"
            )
        _fail(f"Commit failed: {e}. All changes rolled back.")

    elapsed = int((time.monotonic() - start) * 1000)

    return CommitResult(
        commit_id=commit_id,
        vault_path=vault_path,
        page_count=created_count + updated_count,
        created_count=created_count,
        updated_count=updated_count,
        written_paths=written_paths,
        index_path=str(index_path),
        log_path=str(log_path),
        rolled_back=False,
        duration_ms=elapsed,
    )
