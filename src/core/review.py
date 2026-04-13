"""CLI review loop logic. Contract: contracts/s-5-cli-review-loop.contract.md"""

import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.core.llm import complete
from src.core.proposal import Conflict, PageProposal

_VALID_PROVIDER = ("gemini", "lmstudio")
_VALID_CATEGORY = ("sources", "entities", "concepts")
_VALID_ACTION = ("create", "update")
_VALID_REVIEW_ACTION = ("accept", "edit", "reject", "abandon")
_VALID_CONFLICT_DECISION = ("update_in_place", "append_conflict_note")

_ACTION_ALIASES = {
    "a": "accept",
    "accept": "accept",
    "e": "edit",
    "edit": "edit",
    "r": "reject",
    "reject": "reject",
    "x": "abandon",
    "abandon": "abandon",
}

_CONFLICT_DECISION_ALIASES = {
    "1": "update_in_place",
    "u": "update_in_place",
    "update": "update_in_place",
    "update_in_place": "update_in_place",
    "2": "append_conflict_note",
    "a": "append_conflict_note",
    "append": "append_conflict_note",
    "append_conflict_note": "append_conflict_note",
}

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_MAX_BATCH_SIZE = 50
_MAX_CONTENT_LEN = 2_000_000
_MAX_PATH_LEN = 260
_MAX_REJECT_REASON = 1000
_MIN_REJECT_REASON = 5
_MAX_INPUT_RETRIES = 20
_MAX_REPROPOSE_ATTEMPTS = 10


@dataclass
class ConflictDecision:
    existing_page: str
    description: str
    decision: str


@dataclass
class ReviewEvent:
    page_index: int
    title: str
    action: str
    edited: bool
    reject_reason: str | None = None


@dataclass
class ReviewResult:
    approved: list[PageProposal]
    abandoned_titles: list[str]
    events: list[ReviewEvent]


def _fail(msg: str) -> None:
    sys.exit(msg)


def normalize_action(raw: str) -> str:
    token = raw.strip().lower()
    if token in _ACTION_ALIASES:
        return _ACTION_ALIASES[token]
    raise ValueError(
        f"Invalid action '{raw}'. Use one of: {', '.join(_VALID_REVIEW_ACTION)}."
    )


def _validate_string_field(
    value: object, field_name: str, min_len: int, max_len: int
) -> str:
    if not isinstance(value, str):
        _fail(f"Field '{field_name}' must be str.")
    trimmed = value.strip()
    if len(trimmed) < min_len or len(trimmed) > max_len:
        _fail(
            f"Field '{field_name}' length must be {min_len}..{max_len} characters "
            f"after trim, got {len(trimmed)}."
        )
    return trimmed


def validate_proposals(proposals: list[PageProposal]) -> None:
    if not isinstance(proposals, list):
        _fail("proposals must be a list[PageProposal].")
    if len(proposals) > _MAX_BATCH_SIZE:
        _fail(
            f"Batch size exceeds maximum of {_MAX_BATCH_SIZE} proposals, got {len(proposals)}."
        )

    for i, p in enumerate(proposals):
        if not isinstance(p, PageProposal):
            _fail(f"Proposal at index {i} must be PageProposal.")

        _validate_string_field(p.title, f"proposals[{i}].title", 1, 200)
        slug = _validate_string_field(p.slug, f"proposals[{i}].slug", 1, 220)
        if not _SLUG_RE.match(slug):
            _fail(
                f"Field 'proposals[{i}].slug' must match regex "
                "'^[a-z0-9]+(?:-[a-z0-9]+)*$'."
            )

        if p.category not in _VALID_CATEGORY:
            _fail(
                f"Field 'proposals[{i}].category' has invalid value '{p.category}'. "
                f"Must be one of: {', '.join(_VALID_CATEGORY)}."
            )

        content = _validate_string_field(
            p.content, f"proposals[{i}].content", 1, _MAX_CONTENT_LEN
        )
        if not content:
            _fail(f"Field 'proposals[{i}].content' must be non-empty.")

        if p.action not in _VALID_ACTION:
            _fail(
                f"Field 'proposals[{i}].action' has invalid value '{p.action}'. "
                f"Must be one of: {', '.join(_VALID_ACTION)}."
            )

        if not isinstance(p.conflicts, list):
            _fail(f"Field 'proposals[{i}].conflicts' must be list[Conflict].")

        for j, conflict in enumerate(p.conflicts):
            if not isinstance(conflict, Conflict):
                _fail(f"Conflict at proposals[{i}].conflicts[{j}] must be Conflict.")
            _validate_string_field(
                conflict.existing_page,
                f"proposals[{i}].conflicts[{j}].existing_page",
                1,
                _MAX_PATH_LEN,
            )
            _validate_string_field(
                conflict.description,
                f"proposals[{i}].conflicts[{j}].description",
                1,
                2000,
            )
            _validate_string_field(
                conflict.source_ref,
                f"proposals[{i}].conflicts[{j}].source_ref",
                1,
                2048,
            )

        if not isinstance(p.existing_path, str):
            _fail(f"Field 'proposals[{i}].existing_path' must be str.")
        if len(p.existing_path) > _MAX_PATH_LEN:
            _fail(
                f"Field 'proposals[{i}].existing_path' length must be <= {_MAX_PATH_LEN}."
            )

        if p.action == "update" and not p.existing_path.strip():
            _fail(
                f"Field 'proposals[{i}].existing_path' is required when action='update'."
            )
        if p.action == "create" and p.existing_path.strip():
            _fail(
                f"Field 'proposals[{i}].existing_path' must be empty when action='create'."
            )


def _split_editor_command(editor_cmd: str) -> list[str]:
    if os.name == "nt":
        parts = shlex.split(editor_cmd, posix=False)
    else:
        parts = shlex.split(editor_cmd)
    if not parts:
        _fail("Editor command resolved to empty value.")
    return parts


def edit_content(initial_content: str, editor_cmd: str | None = None) -> str:
    if not isinstance(initial_content, str) or not initial_content.strip():
        _fail("initial_content must be non-empty.")

    editor = (editor_cmd or os.environ.get("EDITOR", "")).strip()
    if not editor:
        editor = "nano"

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".md", delete=False
        ) as tf:
            tf.write(initial_content)
            temp_path = Path(tf.name)

        cmd = _split_editor_command(editor)
        cmd.append(str(temp_path))

        try:
            proc = subprocess.run(cmd, check=False)
        except OSError as e:
            _fail(f"Failed to launch editor '{editor}': {e}")

        if proc.returncode != 0:
            _fail(f"Editor exited with non-zero status: {proc.returncode}.")

        edited = temp_path.read_text(encoding="utf-8")
        if not edited.strip():
            _fail("Edited content is empty after save.")
        return edited
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def collect_conflict_decisions(conflicts: list[Conflict]) -> list[ConflictDecision]:
    if not isinstance(conflicts, list):
        _fail("conflicts must be list[Conflict].")

    decisions: list[ConflictDecision] = []
    for i, conflict in enumerate(conflicts):
        if not isinstance(conflict, Conflict):
            _fail(f"Conflict at index {i} must be Conflict.")

        retries = 0
        while True:
            raw = input(
                "Conflict decision [1=update_in_place, 2=append_conflict_note]: "
            ).strip().lower()

            if raw in _CONFLICT_DECISION_ALIASES:
                decision = _CONFLICT_DECISION_ALIASES[raw]
                decisions.append(
                    ConflictDecision(
                        existing_page=conflict.existing_page,
                        description=conflict.description,
                        decision=decision,
                    )
                )
                break

            retries += 1
            if retries >= _MAX_INPUT_RETRIES:
                _fail(
                    "Conflict decision input exceeded retry limit. "
                    f"Valid options: {', '.join(_VALID_CONFLICT_DECISION)}."
                )

    if len(decisions) != len(conflicts):
        _fail("Conflict decision count mismatch.")

    return decisions


def _parse_reproposal_conflicts(
    content: str, existing_path: str, source_ref: str
) -> list[Conflict]:
    out: list[Conflict] = []
    for line in content.splitlines():
        marker_index = line.find("CONFLICT:")
        if marker_index == -1:
            continue
        desc = line[marker_index + len("CONFLICT:") :].strip()
        if desc:
            out.append(
                Conflict(
                    existing_page=existing_path,
                    description=desc,
                    source_ref=source_ref,
                )
            )
    return out


def repropose_page(
    provider: str,
    config,
    env: dict,
    proposal: PageProposal,
    reject_reason: str,
    source_text: str,
    source_meta: dict,
) -> PageProposal:
    if provider not in _VALID_PROVIDER:
        _fail(f"Invalid provider '{provider}'. Must be one of: {', '.join(_VALID_PROVIDER)}.")

    if not isinstance(proposal, PageProposal):
        _fail("proposal must be a PageProposal.")

    reason = _validate_string_field(
        reject_reason, "reject_reason", _MIN_REJECT_REASON, _MAX_REJECT_REASON
    )
    _validate_string_field(source_text, "source_text", 1, _MAX_CONTENT_LEN)
    source_ref = _validate_string_field(
        source_meta.get("source", ""), "source_meta.source", 1, 2048
    )

    system_prompt = (
        "You are revising a wiki page proposal after user rejection.\n"
        "Keep title, category, and action unchanged.\n"
        "Return only markdown content for the revised page."
    )
    user_content = (
        f"TITLE: {proposal.title}\n"
        f"CATEGORY: {proposal.category}\n"
        f"ACTION: {proposal.action}\n"
        f"REJECT_REASON: {reason}\n"
        f"SOURCE_REF: {source_ref}\n\n"
        f"--- ORIGINAL_CONTENT ---\n{proposal.content}\n\n"
        f"--- SOURCE_TEXT ---\n{source_text}"
    )

    new_content = complete(provider, config, env, system_prompt, user_content)
    if not new_content or not new_content.strip():
        _fail("Re-proposal returned empty content.")

    new_conflicts: list[Conflict] = []
    if proposal.action == "update":
        new_conflicts = _parse_reproposal_conflicts(
            new_content, proposal.existing_path, source_ref
        )

    return PageProposal(
        title=proposal.title,
        slug=proposal.slug,
        category=proposal.category,
        content=new_content,
        action=proposal.action,
        conflicts=new_conflicts,
        existing_path=proposal.existing_path,
    )


def _prompt_review_action() -> str:
    retries = 0
    while True:
        raw = input("Action [accept/edit/reject/abandon]: ")
        try:
            return normalize_action(raw)
        except ValueError:
            retries += 1
            if retries >= _MAX_INPUT_RETRIES:
                _fail(
                    "Action input exceeded retry limit. "
                    f"Valid options: {', '.join(_VALID_REVIEW_ACTION)}."
                )


def _prompt_reject_reason() -> str:
    retries = 0
    while True:
        reason = input("Reject reason: ").strip()
        if _MIN_REJECT_REASON <= len(reason) <= _MAX_REJECT_REASON:
            return reason
        retries += 1
        if retries >= _MAX_INPUT_RETRIES:
            _fail(
                "Reject reason input exceeded retry limit. "
                f"Reason must be {_MIN_REJECT_REASON}..{_MAX_REJECT_REASON} chars."
            )


def _apply_conflict_decisions(
    proposal: PageProposal, decisions: list[ConflictDecision]
) -> PageProposal:
    if len(decisions) != len(proposal.conflicts):
        _fail("Conflict decision count mismatch.")

    content = proposal.content
    for conflict, decision in zip(proposal.conflicts, decisions):
        if decision.decision == "append_conflict_note":
            content += (
                f"\n\n[CONFLICT NOTE] {conflict.description} "
                f"(source: {conflict.source_ref})"
            )

    return PageProposal(
        title=proposal.title,
        slug=proposal.slug,
        category=proposal.category,
        content=content,
        action=proposal.action,
        conflicts=proposal.conflicts,
        existing_path=proposal.existing_path,
    )


def review_batch(
    provider: str,
    config,
    env: dict,
    proposals: list[PageProposal],
    source_text: str,
    source_meta: dict,
    on_edit_callback=None,
) -> list[PageProposal]:
    if provider not in _VALID_PROVIDER:
        _fail(f"Invalid provider '{provider}'. Must be one of: {', '.join(_VALID_PROVIDER)}.")

    _validate_string_field(source_text, "source_text", 1, _MAX_CONTENT_LEN)
    _validate_string_field(source_meta.get("source", ""), "source_meta.source", 1, 2048)
    validate_proposals(proposals)

    if not proposals:
        return []

    pending = list(proposals)
    approved: list[PageProposal] = []
    repropose_counts: dict[int, int] = {}

    i = 0
    while i < len(pending):
        current = pending[i]
        action = _prompt_review_action()

        if action == "accept":
            if current.action == "update" and current.conflicts:
                decisions = collect_conflict_decisions(current.conflicts)
                current = _apply_conflict_decisions(current, decisions)
                pending[i] = current
            approved.append(current)
            i += 1
            continue

        if action == "edit":
            edited = edit_content(current.content)
            pending[i] = PageProposal(
                title=current.title,
                slug=current.slug,
                category=current.category,
                content=edited,
                action=current.action,
                conflicts=current.conflicts,
                existing_path=current.existing_path,
            )
            if on_edit_callback:
                updated_remaining = on_edit_callback(current.title, edited, pending[i+1:])
                pending = pending[:i+1] + updated_remaining
            continue

        if action == "reject":
            reason = _prompt_reject_reason()
            attempts = repropose_counts.get(i, 0)
            if attempts >= _MAX_REPROPOSE_ATTEMPTS:
                _fail(
                    "Re-proposal attempts exceeded maximum of "
                    f"{_MAX_REPROPOSE_ATTEMPTS} for current page."
                )
            repropose_counts[i] = attempts + 1
            pending[i] = repropose_page(
                provider,
                config,
                env,
                pending[i],
                reason,
                source_text,
                source_meta,
            )
            continue

        # abandon
        i += 1

    return approved

