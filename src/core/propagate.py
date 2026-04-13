"""Edit propagation. Contract: contracts/s-6-edit-propagation.contract.md"""

import re
import sys

from src.core.llm import complete
from src.core.proposal import PageProposal, Conflict

_CONFLICT_MARKER = "⚠️ CONFLICT:"

_RE_EVALUATE_SYSTEM_PROMPT = """\
You are a wiki editor. A page you previously wrote references another page that the user has just edited.

Revise the page below so it is consistent with the upstream edit. Preserve the page's structure, \
wikilinks, and overall purpose. Only change sections that are affected by the upstream edit.

Rules:
- Write the complete revised page in markdown
- Keep all existing [[wikilinks]]
- If this is an UPDATE to an existing wiki page and the revision introduces contradictions \
with the original existing page, mark each contradiction on its own line:
  ⚠️ CONFLICT: [description of the contradiction]
- Do NOT include the page title as a heading — it will be added automatically"""


def _fail(msg: str) -> None:
    sys.exit(msg)


def find_dependents(edited_title: str, proposals: list[PageProposal]) -> list[int]:
    if not edited_title or not edited_title.strip():
        raise ValueError("edited_title must be non-empty.")

    escaped = re.escape(edited_title)
    pattern = re.compile(r"\[\[" + escaped + r"\]\]", re.IGNORECASE)

    indices: list[int] = []
    for i, proposal in enumerate(proposals):
        if pattern.search(proposal.content):
            indices.append(i)
    return indices


def _re_evaluate_page(
    provider: str,
    config,
    env: dict,
    proposal: PageProposal,
    edited_title: str,
    edited_content: str,
    source_text: str,
    source_meta: dict,
) -> PageProposal:
    user_parts = [
        f"--- PAGE TO REVISE (title: {proposal.title}) ---\n{proposal.content}",
        f"--- UPSTREAM EDIT ({edited_title}) ---\n{edited_content}",
        f"--- ORIGINAL SOURCE TEXT ---\n{source_text}",
    ]
    user_content = "\n\n".join(user_parts)

    new_content = complete(provider, config, env, _RE_EVALUATE_SYSTEM_PROMPT, user_content)

    conflicts: list[Conflict] = []
    if proposal.action == "update" and proposal.existing_path:
        source_ref = source_meta.get("source", "")
        conflicts = _parse_conflicts(new_content, proposal.existing_path, source_ref)

    return PageProposal(
        title=proposal.title,
        slug=proposal.slug,
        category=proposal.category,
        content=new_content,
        action=proposal.action,
        conflicts=conflicts,
        existing_path=proposal.existing_path,
    )


def _parse_conflicts(content: str, existing_page: str, source_ref: str) -> list[Conflict]:
    conflicts: list[Conflict] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(_CONFLICT_MARKER):
            desc = stripped[len(_CONFLICT_MARKER):].strip()
            if desc:
                conflicts.append(Conflict(
                    existing_page=existing_page,
                    description=desc,
                    source_ref=source_ref,
                ))
    return conflicts


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


def propagate_edits(
    edited_title: str,
    edited_content: str,
    pending: list[PageProposal],
    provider: str,
    config,
    env: dict,
    source_text: str,
    source_meta: dict,
) -> list[PageProposal]:
    _validate_string_field(edited_title, "edited_title", 1, 255)
    _validate_string_field(edited_content, "edited_content", 1, 750_000)
    _validate_string_field(source_text, "source_text", 1, 750_000)

    dep_indices = find_dependents(edited_title, pending)
    if not dep_indices:
        return pending

    result = list(pending)

    for idx in dep_indices:
        original = result[idx]
        try:
            updated = _re_evaluate_page(
                provider, config, env, original,
                edited_title, edited_content, source_text, source_meta,
            )
            result[idx] = updated
        except SystemExit:
            print(f"Warning: re-evaluation failed for '{original.title}'. Keeping original.")

    return result
