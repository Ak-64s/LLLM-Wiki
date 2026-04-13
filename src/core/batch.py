"""Batch proposal engine. Contract: contracts/s-4-batch-proposal.contract.md"""

import json
import re
import sys
from pathlib import Path

from src.core.llm import complete
from src.core.proposal import PageProposal, Conflict, slugify, resolve_collision

_VALID_CATEGORIES = ("sources", "entities", "concepts")
_VALID_ACTIONS = ("create", "update")
_CONFLICT_MARKER = "⚠️ CONFLICT:"

_PLAN_SYSTEM_PROMPT = """\
You are a wiki editor. Given a source text and an existing wiki index, determine which wiki pages should be created or updated.

For each page, return a JSON object with:
- "title": human-readable page title
- "action": "create" for new pages, "update" for existing pages that need changes
- "category": one of "sources", "entities", "concepts"
- "existing_page": (only for updates) the relative path of the existing page from the vault root

Rules:
- "sources": create exactly one summary page per ingested source
- "entities": pages for named entities (people, organizations, models, papers)
- "concepts": pages for abstract topics or concepts
- Use [[wikilinks]] in titles to reference other pages

Respond ONLY with a JSON array. No explanation before or after.
Example: [{"title": "Attention Mechanism", "action": "create", "category": "concepts"}]"""

_GENERATE_SYSTEM_PROMPT = """\
You are a wiki editor. Write the content for the following wiki page.

Title: {title}
Category: {category}
Action: {action}

Rules:
- Write in markdown format
- Use [[wikilinks]] to link to related pages. Available pages: {all_titles}
- If this is an UPDATE, include the complete updated page content
- If the update CONTRADICTS existing content, mark each contradiction on its own line:
  ⚠️ CONFLICT: [description of the contradiction]
- Do NOT include the page title as a heading — it will be added automatically"""


def _fail(msg: str) -> None:
    sys.exit(msg)


def generate_batch(
    provider: str,
    config,
    env: dict,
    source_text: str,
    source_meta: dict,
) -> list[PageProposal]:
    if not source_text or not source_text.strip():
        _fail("source_text is empty. Nothing to propose.")

    vault_path = config.vault_path
    index_content = _read_index(vault_path)
    existing_slugs = _list_existing_slugs(vault_path)

    plan = _plan_pages(provider, config, env, source_text, index_content)
    if not plan:
        return []

    all_titles = [entry["title"] for entry in plan]
    used_slugs = set(existing_slugs)
    proposals: list[PageProposal] = []

    for entry in plan:
        title = entry["title"]
        action = entry["action"]
        category = entry["category"]
        existing_page = entry.get("existing_page", "")

        existing_content = ""
        if action == "update" and existing_page:
            existing_content = _load_page(vault_path, existing_page)
            if not existing_content:
                print(f"Warning: update target not found: {existing_page}")

        try:
            content = _generate_page(
                provider, config, env, source_text,
                entry, existing_content, all_titles,
            )
        except SystemExit:
            print(f"Warning: page generation failed for '{title}'. Skipping.")
            continue

        slug = slugify(title)
        slug = resolve_collision(slug, used_slugs)
        used_slugs.add(slug)

        conflicts: list[Conflict] = []
        if action == "update" and existing_page:
            source_ref = source_meta.get("source", "")
            conflicts = _parse_conflicts(content, existing_page, source_ref)

        proposals.append(PageProposal(
            title=title,
            slug=slug,
            category=category,
            content=content,
            action=action,
            conflicts=conflicts,
            existing_path=existing_page if action == "update" else "",
        ))

    return proposals


def _plan_pages(
    provider: str, config, env: dict, source_text: str, index_content: str,
) -> list[dict]:
    user_content_parts = []
    if index_content:
        user_content_parts.append(f"--- EXISTING WIKI INDEX ---\n{index_content}")
    user_content_parts.append(f"--- SOURCE TEXT ---\n{source_text}")
    user_content = "\n\n".join(user_content_parts)

    raw = complete(provider, config, env, _PLAN_SYSTEM_PROMPT, user_content)
    return _parse_plan_json(raw)


def _generate_page(
    provider: str,
    config,
    env: dict,
    source_text: str,
    page_plan: dict,
    existing_content: str,
    all_titles: list[str],
) -> str:
    titles_str = ", ".join(f"[[{t}]]" for t in all_titles)
    system_prompt = _GENERATE_SYSTEM_PROMPT.format(
        title=page_plan["title"],
        category=page_plan["category"],
        action=page_plan["action"],
        all_titles=titles_str,
    )

    user_parts = [f"--- SOURCE TEXT ---\n{source_text}"]
    if existing_content:
        user_parts.append(f"--- EXISTING PAGE CONTENT ---\n{existing_content}")
    user_content = "\n\n".join(user_parts)

    return complete(provider, config, env, system_prompt, user_content)


def _read_index(vault_path: str) -> str:
    p = Path(vault_path) / "wiki" / "index.md"
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def _list_existing_slugs(vault_path: str) -> set[str]:
    slugs: set[str] = set()
    wiki = Path(vault_path) / "wiki"
    for subdir in ("sources", "entities", "concepts"):
        d = wiki / subdir
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.suffix == ".md":
                slugs.add(f.stem)
    return slugs


def _load_page(vault_path: str, relative_path: str) -> str:
    p = Path(vault_path) / relative_path
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def _parse_plan_json(raw: str) -> list[dict]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)

    bracket_start = text.find("[")
    bracket_end = text.rfind("]")
    if bracket_start != -1 and bracket_end != -1 and bracket_end > bracket_start:
        text = text[bracket_start : bracket_end + 1]

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        _fail(f"Phase 1 response is not valid JSON. Raw: {raw[:200]}")

    if not isinstance(data, list):
        _fail("Phase 1 response must be a JSON array, not an object.")

    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            _fail(f"Phase 1 entry {i} is not a JSON object.")
        if "title" not in entry or not entry["title"]:
            _fail(f"Phase 1 entry {i} is missing required field 'title'.")
        if entry.get("action") not in _VALID_ACTIONS:
            _fail(
                f"Phase 1 entry {i} has invalid action '{entry.get('action')}'. "
                f"Must be one of: {', '.join(_VALID_ACTIONS)}."
            )
        if entry.get("category") not in _VALID_CATEGORIES:
            _fail(
                f"Phase 1 entry {i} has invalid category '{entry.get('category')}'. "
                f"Must be one of: {', '.join(_VALID_CATEGORIES)}."
            )

    return data


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
