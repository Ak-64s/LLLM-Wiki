"""S-6 Edit Propagation tests. Contract: contracts/s-6-edit-propagation.contract.md"""

from unittest.mock import patch, MagicMock

import pytest

from src.core.proposal import PageProposal, Conflict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exit_msg(exc_info) -> str:
    return str(exc_info.value.code) if exc_info.value.code is not None else ""


def _make_config():
    from src.core.config import Config
    return Config(
        vault_path="vault",
        sources_path="sources",
        default_provider="gemini",
        lmstudio_endpoint="http://localhost:1234/v1",
        gemini_model="gemini-3-flash-preview",
        chunk_threshold_lmstudio=4000,
        chunk_threshold_gemini=750000,
        chunk_overlap=200,
    )


def _make_proposal(title, slug, category, content, action, conflicts=None, existing_path=""):
    return PageProposal(
        title=title,
        slug=slug,
        category=category,
        content=content,
        action=action,
        conflicts=conflicts or [],
        existing_path=existing_path,
    )


_DEFAULT_ENV = {"GEMINI_API_KEY": "test-key"}
_DEFAULT_META = {"source": "test.txt"}


# ===========================================================================
# find_dependents — Happy Path
# ===========================================================================

class TestFindDependentsHappy:
    """T-6.01 through T-6.03."""

    def test_single_dependent_found(self):
        """T-6.01: Proposal A references [[B]], editing B returns [0]."""
        from src.core.propagate import find_dependents

        proposals = [
            _make_proposal("A", "a", "concepts", "See [[B]] for details.", "create"),
            _make_proposal("B", "b", "concepts", "Core concept.", "create"),
        ]
        result = find_dependents("B", proposals)
        assert result == [0]

    def test_multiple_dependents_found(self):
        """T-6.02: Two proposals reference [[C]], editing C returns [0, 1]."""
        from src.core.propagate import find_dependents

        proposals = [
            _make_proposal("A", "a", "concepts", "Depends on [[C]].", "create"),
            _make_proposal("B", "b", "entities", "Also uses [[C]].", "create"),
            _make_proposal("C", "c", "concepts", "Stand-alone.", "create"),
        ]
        result = find_dependents("C", proposals)
        assert result == [0, 1]

    def test_no_dependents_found(self):
        """T-6.03: No proposals reference [[D]]."""
        from src.core.propagate import find_dependents

        proposals = [
            _make_proposal("A", "a", "concepts", "No links.", "create"),
            _make_proposal("B", "b", "concepts", "Also nothing.", "create"),
            _make_proposal("C", "c", "concepts", "Still nothing.", "create"),
        ]
        result = find_dependents("D", proposals)
        assert result == []


# ===========================================================================
# find_dependents — Edge Cases
# ===========================================================================

class TestFindDependentsEdge:
    """T-6.04 through T-6.08."""

    def test_case_insensitive_match(self):
        """T-6.04: [[attention mechanism]] matches title 'Attention Mechanism'."""
        from src.core.propagate import find_dependents

        proposals = [
            _make_proposal("X", "x", "concepts", "See [[attention mechanism]] here.", "create"),
        ]
        result = find_dependents("Attention Mechanism", proposals)
        assert result == [0]

    def test_substring_does_not_false_match(self):
        """T-6.05: [[Attention Mechanism Overview]] does NOT match title 'Attention Mechanism'."""
        from src.core.propagate import find_dependents

        proposals = [
            _make_proposal("X", "x", "concepts", "See [[Attention Mechanism Overview]].", "create"),
        ]
        result = find_dependents("Attention Mechanism", proposals)
        assert result == []

    def test_multiple_wikilinks_same_proposal(self):
        """T-6.06: Proposal has [[B]] twice, index returned once."""
        from src.core.propagate import find_dependents

        proposals = [
            _make_proposal("A", "a", "concepts", "Links: [[B]] and again [[B]].", "create"),
        ]
        result = find_dependents("B", proposals)
        assert result == [0]

    def test_empty_proposals_list(self):
        """T-6.07: Empty list returns []."""
        from src.core.propagate import find_dependents

        result = find_dependents("B", [])
        assert result == []

    def test_self_reference_is_dependency(self):
        """T-6.08: Proposal B with [[B]] is still a dependent."""
        from src.core.propagate import find_dependents

        proposals = [
            _make_proposal("B", "b", "concepts", "Self-ref: [[B]].", "create"),
        ]
        result = find_dependents("B", proposals)
        assert result == [0]


# ===========================================================================
# find_dependents — Failure Cases
# ===========================================================================

class TestFindDependentsFailure:
    """T-6.09."""

    def test_empty_edited_title(self):
        """T-6.09: Empty edited_title raises ValueError."""
        from src.core.propagate import find_dependents

        with pytest.raises(ValueError):
            find_dependents("", [])


# ===========================================================================
# _re_evaluate_page — Happy Path
# ===========================================================================

class TestReEvaluateHappy:
    """T-6.10 through T-6.12."""

    @patch("src.core.propagate.complete")
    def test_successful_re_evaluation(self, mock_complete):
        """T-6.10: Returns new PageProposal with updated content, same identity fields."""
        from src.core.propagate import _re_evaluate_page

        original = _make_proposal(
            "Page X", "page-x", "concepts", "Old content with [[A]].", "create",
        )
        mock_complete.return_value = "New content after re-evaluation."

        result = _re_evaluate_page(
            "gemini", _make_config(), _DEFAULT_ENV, original,
            "A", "Edited A content.", "Source text.", _DEFAULT_META,
        )

        assert result.title == "Page X"
        assert result.slug == "page-x"
        assert result.category == "concepts"
        assert result.action == "create"
        assert result.existing_path == ""
        assert result.content == "New content after re-evaluation."
        assert result.conflicts == []
        mock_complete.assert_called_once()

    @patch("src.core.propagate.complete")
    def test_re_evaluated_content_has_conflict_markers(self, mock_complete):
        """T-6.11: Update action with conflict markers produces non-empty conflicts."""
        from src.core.propagate import _re_evaluate_page

        original = _make_proposal(
            "Page Y", "page-y", "entities", "Old update content.", "update",
            existing_path="wiki/entities/page-y.md",
        )
        mock_complete.return_value = (
            "Updated content.\n"
            "⚠️ CONFLICT: Date of founding changed from 2020 to 2019.\n"
            "More content."
        )

        result = _re_evaluate_page(
            "gemini", _make_config(), _DEFAULT_ENV, original,
            "A", "Edited A.", "Source text.", {"source": "paper.pdf"},
        )

        assert result.action == "update"
        assert result.content.startswith("Updated content.")
        assert len(result.conflicts) == 1
        assert result.conflicts[0].description == "Date of founding changed from 2020 to 2019."
        assert result.conflicts[0].existing_page == "wiki/entities/page-y.md"
        assert result.conflicts[0].source_ref == "paper.pdf"

    @patch("src.core.propagate.complete")
    def test_create_action_no_conflict_parsing(self, mock_complete):
        """T-6.12: Create action does not parse conflicts even if markers exist."""
        from src.core.propagate import _re_evaluate_page

        original = _make_proposal(
            "Page Z", "page-z", "concepts",
            "Content with [[A]].", "create",
        )
        mock_complete.return_value = (
            "New content.\n"
            "⚠️ CONFLICT: Something contradictory.\n"
        )

        result = _re_evaluate_page(
            "gemini", _make_config(), _DEFAULT_ENV, original,
            "A", "Edited A.", "Source text.", _DEFAULT_META,
        )

        assert result.action == "create"
        assert result.conflicts == []


# ===========================================================================
# _re_evaluate_page — Failure Cases
# ===========================================================================

class TestReEvaluateFailure:
    """T-6.13."""

    @patch("src.core.propagate.complete")
    def test_llm_failure_raises_system_exit(self, mock_complete):
        """T-6.13: SystemExit from complete() propagates."""
        from src.core.propagate import _re_evaluate_page

        mock_complete.side_effect = SystemExit("LLM error")
        original = _make_proposal("P", "p", "concepts", "Content [[A]].", "create")

        with pytest.raises(SystemExit):
            _re_evaluate_page(
                "gemini", _make_config(), _DEFAULT_ENV, original,
                "A", "Edited A.", "Source text.", _DEFAULT_META,
            )


# ===========================================================================
# propagate_edits — Happy Path
# ===========================================================================

class TestPropagateEditsHappy:
    """T-6.14 through T-6.16."""

    @patch("src.core.propagate.complete")
    def test_single_dependent_re_evaluated(self, mock_complete):
        """T-6.14: Middle proposal depends on A, gets re-evaluated."""
        from src.core.propagate import propagate_edits

        proposals = [
            _make_proposal("X", "x", "concepts", "No links.", "create"),
            _make_proposal("Y", "y", "concepts", "Uses [[A]].", "create"),
            _make_proposal("Z", "z", "concepts", "Independent.", "create"),
        ]
        mock_complete.return_value = "Re-evaluated Y content."

        result = propagate_edits(
            "A", "Edited A content.", proposals,
            "gemini", _make_config(), _DEFAULT_ENV, "Source text.", _DEFAULT_META,
        )

        assert len(result) == 3
        assert result[0].content == "No links."
        assert result[1].content == "Re-evaluated Y content."
        assert result[2].content == "Independent."
        mock_complete.assert_called_once()

    @patch("src.core.propagate.complete")
    def test_multiple_dependents_all_re_evaluated(self, mock_complete):
        """T-6.15: First two proposals depend on C, both re-evaluated."""
        from src.core.propagate import propagate_edits

        proposals = [
            _make_proposal("A", "a", "concepts", "Links [[C]].", "create"),
            _make_proposal("B", "b", "entities", "Also [[C]].", "create"),
            _make_proposal("C", "c", "concepts", "Stand-alone.", "create"),
        ]
        mock_complete.side_effect = ["Re-eval A.", "Re-eval B."]

        result = propagate_edits(
            "C", "New C content.", proposals,
            "gemini", _make_config(), _DEFAULT_ENV, "Source text.", _DEFAULT_META,
        )

        assert len(result) == 3
        assert result[0].content == "Re-eval A."
        assert result[1].content == "Re-eval B."
        assert result[2].content == "Stand-alone."
        assert mock_complete.call_count == 2

    @patch("src.core.propagate.complete")
    def test_no_dependents_unchanged(self, mock_complete):
        """T-6.16: No proposals reference D; list returned unchanged, no LLM calls."""
        from src.core.propagate import propagate_edits

        proposals = [
            _make_proposal("A", "a", "concepts", "No links.", "create"),
            _make_proposal("B", "b", "concepts", "Nothing here.", "create"),
            _make_proposal("C", "c", "concepts", "Still nothing.", "create"),
        ]

        result = propagate_edits(
            "D", "Edited D.", proposals,
            "gemini", _make_config(), _DEFAULT_ENV, "Source text.", _DEFAULT_META,
        )

        assert len(result) == 3
        for i in range(3):
            assert result[i] is proposals[i]
        mock_complete.assert_not_called()


# ===========================================================================
# propagate_edits — Edge Cases
# ===========================================================================

class TestPropagateEditsEdge:
    """T-6.17 through T-6.21."""

    @patch("src.core.propagate.complete")
    def test_re_evaluation_failure_keeps_original(self, mock_complete, capsys):
        """T-6.17: First fails, second succeeds. First keeps original."""
        from src.core.propagate import propagate_edits

        proposals = [
            _make_proposal("P1", "p1", "concepts", "Ref [[A]].", "create"),
            _make_proposal("P2", "p2", "concepts", "Ref [[A]].", "create"),
        ]
        mock_complete.side_effect = [SystemExit("LLM fail"), "Re-eval P2."]

        result = propagate_edits(
            "A", "Edited A.", proposals,
            "gemini", _make_config(), _DEFAULT_ENV, "Source text.", _DEFAULT_META,
        )

        assert len(result) == 2
        assert result[0].content == "Ref [[A]]."
        assert result[1].content == "Re-eval P2."
        captured = capsys.readouterr()
        assert "P1" in captured.out

    @patch("src.core.propagate.complete")
    def test_all_re_evaluations_fail(self, mock_complete, capsys):
        """T-6.18: All fail; both keep originals. Warnings printed."""
        from src.core.propagate import propagate_edits

        proposals = [
            _make_proposal("P1", "p1", "concepts", "Ref [[A]].", "create"),
            _make_proposal("P2", "p2", "concepts", "Ref [[A]].", "create"),
        ]
        mock_complete.side_effect = [SystemExit("fail1"), SystemExit("fail2")]

        result = propagate_edits(
            "A", "Edited A.", proposals,
            "gemini", _make_config(), _DEFAULT_ENV, "Source text.", _DEFAULT_META,
        )

        assert len(result) == 2
        assert result[0].content == "Ref [[A]]."
        assert result[1].content == "Ref [[A]]."
        captured = capsys.readouterr()
        assert "P1" in captured.out
        assert "P2" in captured.out

    @patch("src.core.propagate.complete")
    def test_empty_pending_list(self, mock_complete):
        """T-6.19: Empty pending returns []."""
        from src.core.propagate import propagate_edits

        result = propagate_edits(
            "A", "Edited A.", [],
            "gemini", _make_config(), _DEFAULT_ENV, "Source text.", _DEFAULT_META,
        )

        assert result == []
        mock_complete.assert_not_called()

    @patch("src.core.propagate.complete")
    def test_order_preserved(self, mock_complete):
        """T-6.20: 5 proposals, indices 1 and 3 depend; order preserved."""
        from src.core.propagate import propagate_edits

        proposals = [
            _make_proposal("P0", "p0", "concepts", "Independent.", "create"),
            _make_proposal("P1", "p1", "concepts", "Uses [[E]].", "create"),
            _make_proposal("P2", "p2", "concepts", "Independent too.", "create"),
            _make_proposal("P3", "p3", "entities", "Also [[E]].", "create"),
            _make_proposal("P4", "p4", "concepts", "No ref.", "create"),
        ]
        mock_complete.side_effect = ["New P1.", "New P3."]

        result = propagate_edits(
            "E", "Edited E.", proposals,
            "gemini", _make_config(), _DEFAULT_ENV, "Source text.", _DEFAULT_META,
        )

        assert len(result) == 5
        assert result[0].content == "Independent."
        assert result[1].content == "New P1."
        assert result[2].content == "Independent too."
        assert result[3].content == "New P3."
        assert result[4].content == "No ref."
        assert result[0].title == "P0"
        assert result[1].title == "P1"
        assert result[2].title == "P2"
        assert result[3].title == "P3"
        assert result[4].title == "P4"

    @patch("src.core.propagate.complete")
    def test_proposal_fields_preserved(self, mock_complete):
        """T-6.21: title, slug, category, action, existing_path unchanged after re-eval."""
        from src.core.propagate import propagate_edits

        proposals = [
            _make_proposal(
                "Target", "target", "entities", "Content with [[A]].", "update",
                existing_path="wiki/entities/target.md",
            ),
        ]
        mock_complete.return_value = "New content."

        result = propagate_edits(
            "A", "Edited A.", proposals,
            "gemini", _make_config(), _DEFAULT_ENV, "Source text.", _DEFAULT_META,
        )

        assert len(result) == 1
        p = result[0]
        assert p.title == "Target"
        assert p.slug == "target"
        assert p.category == "entities"
        assert p.action == "update"
        assert p.existing_path == "wiki/entities/target.md"
        assert p.content == "New content."


# ===========================================================================
# propagate_edits — Failure Cases
# ===========================================================================

class TestPropagateEditsFailure:
    """T-6.22 through T-6.25."""

    def test_empty_edited_title(self):
        """T-6.22: Empty edited_title raises SystemExit."""
        from src.core.propagate import propagate_edits

        with pytest.raises(SystemExit) as exc_info:
            propagate_edits(
                "", "Content.", [],
                "gemini", _make_config(), _DEFAULT_ENV, "Source.", _DEFAULT_META,
            )
        assert "length" in _exit_msg(exc_info).lower()

    def test_empty_edited_content(self):
        """T-6.23: Empty edited_content raises SystemExit."""
        from src.core.propagate import propagate_edits

        with pytest.raises(SystemExit) as exc_info:
            propagate_edits(
                "A", "", [],
                "gemini", _make_config(), _DEFAULT_ENV, "Source.", _DEFAULT_META,
            )
        assert "length" in _exit_msg(exc_info).lower()

    def test_empty_source_text(self):
        """T-6.24: Empty source_text raises SystemExit."""
        from src.core.propagate import propagate_edits

        with pytest.raises(SystemExit) as exc_info:
            propagate_edits(
                "A", "Content.", [],
                "gemini", _make_config(), _DEFAULT_ENV, "", _DEFAULT_META,
            )
        assert "length" in _exit_msg(exc_info).lower()

    def test_whitespace_only_edited_title(self):
        """T-6.25: Whitespace-only edited_title raises SystemExit."""
        from src.core.propagate import propagate_edits

        with pytest.raises(SystemExit) as exc_info:
            propagate_edits(
                "   ", "Content.", [],
                "gemini", _make_config(), _DEFAULT_ENV, "Source.", _DEFAULT_META,
            )
        assert "length" in _exit_msg(exc_info).lower()

    def test_edited_title_too_long(self):
        """edited_title exceeds 255 chars."""
        from src.core.propagate import propagate_edits

        with pytest.raises(SystemExit) as exc_info:
            propagate_edits(
                "A" * 256, "Content.", [],
                "gemini", _make_config(), _DEFAULT_ENV, "Source.", _DEFAULT_META,
            )
        assert "length" in _exit_msg(exc_info).lower()

    def test_edited_content_too_long(self):
        """edited_content exceeds 750,000 chars."""
        from src.core.propagate import propagate_edits

        with pytest.raises(SystemExit) as exc_info:
            propagate_edits(
                "Title", "B" * 750001, [],
                "gemini", _make_config(), _DEFAULT_ENV, "Source.", _DEFAULT_META,
            )
        assert "length" in _exit_msg(exc_info).lower()

    def test_source_text_too_long(self):
        """source_text exceeds 750,000 chars."""
        from src.core.propagate import propagate_edits

        with pytest.raises(SystemExit) as exc_info:
            propagate_edits(
                "Title", "Content.", [],
                "gemini", _make_config(), _DEFAULT_ENV, "S" * 750001, _DEFAULT_META,
            )
        assert "length" in _exit_msg(exc_info).lower()
