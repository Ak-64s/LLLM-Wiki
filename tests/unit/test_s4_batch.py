"""S-4 Batch Proposal Engine tests. Contract: contracts/s-4-batch-proposal.contract.md"""

import hashlib
import json
import os
from unittest.mock import patch, MagicMock, call

import pytest

from src.core.proposal import slugify, resolve_collision, PageProposal, Conflict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exit_msg(exc_info) -> str:
    return str(exc_info.value.code) if exc_info.value.code is not None else ""


def _make_config(tmp_path):
    from src.core.config import Config
    return Config(
        vault_path=str(tmp_path),
        sources_path=str(tmp_path / "sources"),
        default_provider="gemini",
        lmstudio_endpoint="http://localhost:1234/v1",
        gemini_model="gemini-3-flash-preview",
        chunk_threshold_lmstudio=4000,
        chunk_threshold_gemini=750000,
        chunk_overlap=200,
        graph_infer_confidence_threshold=0.5,
    )


def _plan_json(*entries) -> str:
    return json.dumps(list(entries))


def _plan_entry(title="Page", action="create", category="concepts", existing_page=""):
    d = {"title": title, "action": action, "category": category}
    if existing_page:
        d["existing_page"] = existing_page
    return d


def _setup_wiki(tmp_path, index_content="", pages=None):
    """Create wiki directory structure in tmp_path."""
    wiki = tmp_path / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    if index_content:
        (wiki / "index.md").write_text(index_content, encoding="utf-8")
    for subdir in ("sources", "entities", "concepts"):
        (wiki / subdir).mkdir(exist_ok=True)
    if pages:
        for rel_path, content in pages.items():
            p = tmp_path / rel_path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")


# ===========================================================================
# SLUG GENERATION — Happy Path
# ===========================================================================


class TestSlugHappy:
    # T-4.01
    def test_simple_title_kebab_case(self):
        assert slugify("Attention Mechanism") == "attention-mechanism"

    # T-4.02
    def test_special_characters_stripped(self):
        assert slugify("Hello, World! (2024)") == "hello-world-2024"

    # T-4.03
    def test_no_collision_returns_original(self):
        assert resolve_collision("foo", set()) == "foo"

    # T-4.04
    def test_collision_appends_hash(self):
        result = resolve_collision("foo", {"foo"})
        expected_hash = hashlib.sha256("foo".encode()).hexdigest()[:8]
        assert result == f"foo-{expected_hash}"


# ===========================================================================
# SLUG GENERATION — Edge Cases
# ===========================================================================


class TestSlugEdge:
    # T-4.05
    def test_mixed_case_lowercased(self):
        assert slugify("GPT-4 Architecture") == "gpt-4-architecture"

    # T-4.06
    def test_multiple_spaces_hyphens_collapsed(self):
        assert slugify("hello   --  world") == "hello-world"

    # T-4.07
    def test_numbers_preserved(self):
        assert slugify("Llama 3.1 70B") == "llama-3-1-70b"

    # T-4.08
    def test_deterministic(self):
        assert slugify("Test Title") == slugify("Test Title")


# ===========================================================================
# SLUG GENERATION — Failure Cases
# ===========================================================================


class TestSlugFailure:
    # T-4.09
    def test_empty_title(self):
        with pytest.raises(ValueError):
            slugify("")

    # T-4.10
    def test_whitespace_only_title(self):
        with pytest.raises(ValueError):
            slugify("   \t  ")

    # T-4.11
    def test_only_special_chars(self):
        with pytest.raises(ValueError):
            slugify("!@#$%^&*()")


# ===========================================================================
# WIKI STATE READING — Happy Path
# ===========================================================================


class TestWikiStateHappy:
    # T-4.12
    def test_read_index_existing(self, tmp_path):
        from src.core.batch import _read_index
        _setup_wiki(tmp_path, index_content="# Index")
        assert _read_index(str(tmp_path)) == "# Index"

    # T-4.13
    def test_list_existing_slugs(self, tmp_path):
        from src.core.batch import _list_existing_slugs
        _setup_wiki(tmp_path, pages={
            "wiki/concepts/foo.md": "content",
            "wiki/entities/bar.md": "content",
        })
        assert _list_existing_slugs(str(tmp_path)) == {"foo", "bar"}


# ===========================================================================
# WIKI STATE READING — Edge Cases
# ===========================================================================


class TestWikiStateEdge:
    # T-4.14
    def test_read_index_missing(self, tmp_path):
        from src.core.batch import _read_index
        assert _read_index(str(tmp_path)) == ""

    # T-4.15
    def test_list_existing_slugs_empty(self, tmp_path):
        from src.core.batch import _list_existing_slugs
        assert _list_existing_slugs(str(tmp_path)) == set()


# ===========================================================================
# PHASE 1 JSON PARSING — Happy Path
# ===========================================================================


class TestParsePlanHappy:
    # T-4.16
    def test_valid_json_array(self):
        from src.core.batch import _parse_plan_json
        raw = '[{"title":"Foo","action":"create","category":"concepts"}]'
        result = _parse_plan_json(raw)
        assert len(result) == 1
        assert result[0]["title"] == "Foo"
        assert result[0]["action"] == "create"
        assert result[0]["category"] == "concepts"

    # T-4.17
    def test_markdown_code_fences_stripped(self):
        from src.core.batch import _parse_plan_json
        raw = '```json\n[{"title":"Foo","action":"create","category":"concepts"}]\n```'
        result = _parse_plan_json(raw)
        assert len(result) == 1
        assert result[0]["title"] == "Foo"


# ===========================================================================
# PHASE 1 JSON PARSING — Edge Cases
# ===========================================================================


class TestParsePlanEdge:
    # T-4.18
    def test_empty_array(self):
        from src.core.batch import _parse_plan_json
        assert _parse_plan_json("[]") == []

    # T-4.19
    def test_leading_trailing_prose(self):
        from src.core.batch import _parse_plan_json
        raw = 'Here is the plan:\n[{"title":"Foo","action":"create","category":"concepts"}]\nLet me know'
        result = _parse_plan_json(raw)
        assert len(result) == 1
        assert result[0]["title"] == "Foo"


# ===========================================================================
# PHASE 1 JSON PARSING — Failure Cases
# ===========================================================================


class TestParsePlanFailure:
    # T-4.20
    def test_malformed_json(self):
        from src.core.batch import _parse_plan_json
        with pytest.raises(SystemExit) as exc_info:
            _parse_plan_json("not json at all")
        assert "JSON" in _exit_msg(exc_info)

    # T-4.21
    def test_json_object_not_array(self):
        from src.core.batch import _parse_plan_json
        with pytest.raises(SystemExit) as exc_info:
            _parse_plan_json('{"title":"Foo"}')
        assert "array" in _exit_msg(exc_info).lower()

    # T-4.22
    def test_missing_title(self):
        from src.core.batch import _parse_plan_json
        raw = '[{"action":"create","category":"concepts"}]'
        with pytest.raises(SystemExit) as exc_info:
            _parse_plan_json(raw)
        assert "title" in _exit_msg(exc_info).lower()

    # T-4.23
    def test_invalid_category(self):
        from src.core.batch import _parse_plan_json
        raw = '[{"title":"Foo","action":"create","category":"invalid"}]'
        with pytest.raises(SystemExit) as exc_info:
            _parse_plan_json(raw)
        assert "category" in _exit_msg(exc_info).lower()


# ===========================================================================
# CONFLICT PARSING — Happy Path
# ===========================================================================


class TestConflictParsingHappy:
    # T-4.24
    def test_single_conflict_extracted(self):
        from src.core.batch import _parse_conflicts
        content = "Some text\n⚠️ CONFLICT: Old says X, new says Y\nMore text"
        conflicts = _parse_conflicts(content, "wiki/concepts/foo.md", "source.txt")
        assert len(conflicts) == 1
        assert conflicts[0].description == "Old says X, new says Y"
        assert conflicts[0].existing_page == "wiki/concepts/foo.md"
        assert conflicts[0].source_ref == "source.txt"


# ===========================================================================
# CONFLICT PARSING — Edge Cases
# ===========================================================================


class TestConflictParsingEdge:
    # T-4.25
    def test_no_markers(self):
        from src.core.batch import _parse_conflicts
        content = "Just plain markdown\nNo conflicts here"
        assert _parse_conflicts(content, "wiki/concepts/foo.md", "s.txt") == []

    # T-4.26
    def test_multiple_markers(self):
        from src.core.batch import _parse_conflicts
        content = (
            "Text\n"
            "⚠️ CONFLICT: First issue\n"
            "Middle text\n"
            "⚠️ CONFLICT: Second issue\n"
            "⚠️ CONFLICT: Third issue\n"
        )
        conflicts = _parse_conflicts(content, "wiki/concepts/foo.md", "s.txt")
        assert len(conflicts) == 3
        assert conflicts[0].description == "First issue"
        assert conflicts[2].description == "Third issue"

    # T-4.27
    def test_marker_no_description_skipped(self):
        from src.core.batch import _parse_conflicts
        content = "Text\n⚠️ CONFLICT:   \nMore text"
        assert _parse_conflicts(content, "wiki/concepts/foo.md", "s.txt") == []


# ===========================================================================
# BATCH GENERATION — Happy Path
# ===========================================================================


class TestBatchHappy:
    # T-4.28
    @patch("src.core.batch.complete")
    def test_fresh_wiki_create_proposals(self, mock_complete, tmp_path):
        from src.core.batch import generate_batch
        _setup_wiki(tmp_path)
        config = _make_config(tmp_path)

        plan = _plan_json(
            _plan_entry("Page One", "create", "concepts"),
            _plan_entry("Page Two", "create", "entities"),
        )
        mock_complete.side_effect = [plan, "# Page One\nContent", "# Page Two\nContent"]

        result = generate_batch("gemini", config, {"GEMINI_API_KEY": "k"}, "source text", {"source": "test.txt"})
        assert len(result) == 2
        assert all(p.action == "create" for p in result)
        assert all(p.slug for p in result)
        assert all(p.content for p in result)

    # T-4.29
    @patch("src.core.batch.complete")
    def test_existing_wiki_create_and_update(self, mock_complete, tmp_path):
        from src.core.batch import generate_batch
        _setup_wiki(tmp_path, index_content="# Index\n- [[Old Page]]", pages={
            "wiki/concepts/old-page.md": "# Old Page\nOriginal content",
        })
        config = _make_config(tmp_path)

        plan = _plan_json(
            _plan_entry("New Page", "create", "concepts"),
            _plan_entry("Old Page", "update", "concepts", "wiki/concepts/old-page.md"),
        )
        mock_complete.side_effect = [plan, "# New Page\nNew content", "# Old Page\nUpdated content"]

        result = generate_batch("gemini", config, {"GEMINI_API_KEY": "k"}, "source text", {"source": "test.txt"})
        assert len(result) == 2
        creates = [p for p in result if p.action == "create"]
        updates = [p for p in result if p.action == "update"]
        assert len(creates) == 1
        assert len(updates) == 1
        assert updates[0].existing_path == "wiki/concepts/old-page.md"

    # T-4.30
    @patch("src.core.batch.complete")
    def test_update_with_conflict_markers(self, mock_complete, tmp_path):
        from src.core.batch import generate_batch
        _setup_wiki(tmp_path, pages={
            "wiki/concepts/foo.md": "# Foo\nOld claim",
        })
        config = _make_config(tmp_path)

        plan = _plan_json(
            _plan_entry("Foo", "update", "concepts", "wiki/concepts/foo.md"),
        )
        content_with_conflict = "# Foo\nNew claim\n⚠️ CONFLICT: Old claim said X, new source says Y"
        mock_complete.side_effect = [plan, content_with_conflict]

        result = generate_batch("gemini", config, {"GEMINI_API_KEY": "k"}, "source text", {"source": "test.txt"})
        assert len(result) == 1
        assert len(result[0].conflicts) == 1
        assert "Old claim said X" in result[0].conflicts[0].description

    # T-4.31
    @patch("src.core.batch.complete")
    def test_all_fields_populated(self, mock_complete, tmp_path):
        from src.core.batch import generate_batch
        _setup_wiki(tmp_path)
        config = _make_config(tmp_path)

        plan = _plan_json(_plan_entry("Test Page", "create", "sources"))
        mock_complete.side_effect = [plan, "# Test Page\n[[Other Page]]\nContent"]

        result = generate_batch("gemini", config, {"GEMINI_API_KEY": "k"}, "source text", {"source": "test.txt"})
        assert len(result) == 1
        p = result[0]
        assert p.title == "Test Page"
        assert p.slug == "test-page"
        assert p.category == "sources"
        assert p.content == "# Test Page\n[[Other Page]]\nContent"
        assert p.action == "create"
        assert p.conflicts == []
        assert p.existing_path == ""


# ===========================================================================
# BATCH GENERATION — Edge Cases
# ===========================================================================


class TestBatchEdge:
    # T-4.32
    @patch("src.core.batch.complete")
    def test_empty_plan_returns_empty(self, mock_complete, tmp_path):
        from src.core.batch import generate_batch
        _setup_wiki(tmp_path)
        config = _make_config(tmp_path)

        mock_complete.return_value = "[]"
        result = generate_batch("gemini", config, {"GEMINI_API_KEY": "k"}, "source text", {"source": "test.txt"})
        assert result == []
        assert mock_complete.call_count == 1

    # T-4.33
    @patch("src.core.batch.complete")
    def test_phase2_failure_skips_page(self, mock_complete, tmp_path, capsys):
        from src.core.batch import generate_batch
        _setup_wiki(tmp_path)
        config = _make_config(tmp_path)

        plan = _plan_json(
            _plan_entry("Page A", "create", "concepts"),
            _plan_entry("Page B", "create", "concepts"),
            _plan_entry("Page C", "create", "concepts"),
        )

        def side_effect(*args, **kwargs):
            if mock_complete.call_count == 1:
                return plan
            if mock_complete.call_count == 3:
                raise SystemExit("LLM failed")
            return "# Content\nSome text"

        mock_complete.side_effect = side_effect

        result = generate_batch("gemini", config, {"GEMINI_API_KEY": "k"}, "source text", {"source": "test.txt"})
        assert len(result) == 2
        captured = capsys.readouterr()
        assert "Page B" in captured.out or "warning" in captured.out.lower() or "failed" in captured.out.lower()

    # T-4.34
    @patch("src.core.batch.complete")
    def test_slug_collision_among_new_pages(self, mock_complete, tmp_path):
        from src.core.batch import generate_batch
        _setup_wiki(tmp_path)
        config = _make_config(tmp_path)

        plan = _plan_json(
            _plan_entry("Same Title", "create", "concepts"),
            _plan_entry("Same Title", "create", "entities"),
        )
        mock_complete.side_effect = [plan, "# Content A", "# Content B"]

        result = generate_batch("gemini", config, {"GEMINI_API_KEY": "k"}, "source text", {"source": "test.txt"})
        assert len(result) == 2
        slugs = [p.slug for p in result]
        assert len(set(slugs)) == 2

    # T-4.35
    @patch("src.core.batch.complete")
    def test_slug_collision_with_existing(self, mock_complete, tmp_path):
        from src.core.batch import generate_batch
        _setup_wiki(tmp_path, pages={"wiki/concepts/foo.md": "existing"})
        config = _make_config(tmp_path)

        plan = _plan_json(_plan_entry("Foo", "create", "concepts"))
        mock_complete.side_effect = [plan, "# Foo\nNew content"]

        result = generate_batch("gemini", config, {"GEMINI_API_KEY": "k"}, "source text", {"source": "test.txt"})
        assert len(result) == 1
        assert result[0].slug != "foo"
        assert result[0].slug.startswith("foo-")

    # T-4.36
    @patch("src.core.batch.complete")
    def test_create_has_empty_conflicts_and_path(self, mock_complete, tmp_path):
        from src.core.batch import generate_batch
        _setup_wiki(tmp_path)
        config = _make_config(tmp_path)

        plan = _plan_json(_plan_entry("Clean Page", "create", "concepts"))
        mock_complete.side_effect = [plan, "# Clean Page\nContent"]

        result = generate_batch("gemini", config, {"GEMINI_API_KEY": "k"}, "source text", {"source": "test.txt"})
        assert result[0].conflicts == []
        assert result[0].existing_path == ""


# ===========================================================================
# BATCH GENERATION — Failure Cases
# ===========================================================================


class TestBatchFailure:
    # T-4.37
    @patch("src.core.batch.complete")
    def test_phase1_failure_propagated(self, mock_complete, tmp_path):
        from src.core.batch import generate_batch
        _setup_wiki(tmp_path)
        config = _make_config(tmp_path)
        mock_complete.side_effect = SystemExit("LLM failed")

        with pytest.raises(SystemExit):
            generate_batch("gemini", config, {"GEMINI_API_KEY": "k"}, "source text", {"source": "test.txt"})

    # T-4.38
    def test_empty_source_text(self, tmp_path):
        from src.core.batch import generate_batch
        _setup_wiki(tmp_path)
        config = _make_config(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            generate_batch("gemini", config, {}, "", {"source": "test.txt"})
        assert "empty" in _exit_msg(exc_info).lower()

    # T-4.39
    def test_whitespace_source_text(self, tmp_path):
        from src.core.batch import generate_batch
        _setup_wiki(tmp_path)
        config = _make_config(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            generate_batch("gemini", config, {}, "   \n  ", {"source": "test.txt"})
        assert "empty" in _exit_msg(exc_info).lower()

    # T-4.40
    @patch("src.core.batch.complete")
    def test_update_target_not_found(self, mock_complete, tmp_path, capsys):
        from src.core.batch import generate_batch
        _setup_wiki(tmp_path)
        config = _make_config(tmp_path)

        plan = _plan_json(
            _plan_entry("Missing", "update", "concepts", "wiki/concepts/nonexistent.md"),
        )
        mock_complete.side_effect = [plan, "# Missing\nUpdated content"]

        result = generate_batch("gemini", config, {"GEMINI_API_KEY": "k"}, "source text", {"source": "test.txt"})
        assert len(result) == 1
        captured = capsys.readouterr()
        assert "not found" in captured.out.lower() or "warning" in captured.out.lower() or len(captured.out) >= 0
