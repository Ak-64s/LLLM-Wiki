"""S-5 CLI Review Loop tests. Contract: contracts/s-5-cli-review-loop.contract.md"""

from unittest.mock import MagicMock, patch

import pytest

from src.core.config import Config
from src.core.proposal import Conflict, PageProposal
from src.core.review import (
    collect_conflict_decisions,
    edit_content,
    normalize_action,
    repropose_page,
    review_batch,
    validate_proposals,
)


def _exit_msg(exc_info) -> str:
    return str(exc_info.value.code) if exc_info.value.code is not None else ""


def _config() -> Config:
    return Config(
        vault_path="vault",
        sources_path="sources",
        default_provider="gemini",
        lmstudio_endpoint="http://localhost:1234/v1",
        gemini_model="gemini-3-flash-preview",
        chunk_threshold_lmstudio=4000,
        chunk_threshold_gemini=750000,
        chunk_overlap=200,
        graph_infer_confidence_threshold=0.5,
    )


def _proposal(
    *,
    title: str = "Transformer Architecture",
    slug: str = "transformer-architecture",
    category: str = "concepts",
    content: str = "Initial content",
    action: str = "create",
    conflicts: list[Conflict] | None = None,
    existing_path: str = "",
) -> PageProposal:
    return PageProposal(
        title=title,
        slug=slug,
        category=category,
        content=content,
        action=action,
        conflicts=conflicts or [],
        existing_path=existing_path,
    )


# ===========================================================================
# Happy Path
# ===========================================================================


class TestReviewHappy:
    # T-5.01
    def test_accept_single_proposal(self):
        proposals = [_proposal()]
        with patch("builtins.input", side_effect=["accept"]):
            approved = review_batch(
                "gemini",
                _config(),
                {"GEMINI_API_KEY": "k"},
                proposals,
                "source text",
                {"source": "note.md"},
            )
        assert len(approved) == 1
        assert approved[0].title == "Transformer Architecture"

    # T-5.03
    def test_edit_then_accept(self):
        proposals = [_proposal(content="Before")]
        with patch("builtins.input", side_effect=["edit", "accept"]):
            with patch("src.core.review.edit_content", return_value="After"):
                approved = review_batch(
                    "gemini",
                    _config(),
                    {"GEMINI_API_KEY": "k"},
                    proposals,
                    "source text",
                    {"source": "note.md"},
                )
        assert len(approved) == 1
        assert approved[0].content == "After"

    # T-5.04
    def test_reject_then_accept_reproposal(self):
        proposals = [_proposal(content="Old")]
        replacement = _proposal(content="New")
        with patch("builtins.input", side_effect=["reject", "reason", "accept"]):
            with patch("src.core.review.repropose_page", return_value=replacement):
                approved = review_batch(
                    "gemini",
                    _config(),
                    {"GEMINI_API_KEY": "k"},
                    proposals,
                    "source text",
                    {"source": "note.md"},
                )
        assert len(approved) == 1
        assert approved[0].content == "New"

    # T-5.06
    def test_abandon_proposal(self):
        proposals = [_proposal()]
        with patch("builtins.input", side_effect=["abandon"]):
            approved = review_batch(
                "gemini",
                _config(),
                {"GEMINI_API_KEY": "k"},
                proposals,
                "source text",
                {"source": "note.md"},
            )
        assert approved == []

    # T-5.05
    def test_collect_conflict_decisions_two_conflicts(self):
        conflicts = [
            Conflict(existing_page="wiki/concepts/x.md", description="desc1", source_ref="a"),
            Conflict(existing_page="wiki/concepts/y.md", description="desc2", source_ref="b"),
        ]
        with patch("builtins.input", side_effect=["1", "2"]):
            decisions = collect_conflict_decisions(conflicts)
        assert len(decisions) == 2
        assert decisions[0].decision == "update_in_place"
        assert decisions[1].decision == "append_conflict_note"


# ===========================================================================
# Edge Cases
# ===========================================================================


class TestReviewEdge:
    # T-5.07
    def test_empty_batch_returns_empty(self):
        approved = review_batch(
            "gemini",
            _config(),
            {"GEMINI_API_KEY": "k"},
            [],
            "source text",
            {"source": "note.md"},
        )
        assert approved == []

    # T-5.08
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("a", "accept"),
            ("e", "edit"),
            ("r", "reject"),
            ("x", "abandon"),
        ],
    )
    def test_normalize_action_aliases(self, raw, expected):
        assert normalize_action(raw) == expected

    # T-5.09
    def test_normalize_action_whitespace_and_case(self):
        assert normalize_action("  AcCePt  ") == "accept"

    # T-5.10
    def test_edit_content_uses_nano_fallback_when_editor_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            with patch("src.core.review.subprocess.run", return_value=mock_proc) as run_mock:
                out = edit_content("hello")
        assert out == "hello"
        cmd = run_mock.call_args.args[0]
        assert cmd[0] == "nano"

    # T-5.11
    def test_update_with_no_conflicts_does_not_prompt_conflicts(self):
        p = _proposal(action="update", existing_path="wiki/concepts/transformer-architecture.md")
        with patch("builtins.input", side_effect=["accept"]):
            approved = review_batch(
                "gemini",
                _config(),
                {"GEMINI_API_KEY": "k"},
                [p],
                "source text",
                {"source": "note.md"},
            )
        assert len(approved) == 1


# ===========================================================================
# Failure Cases
# ===========================================================================


class TestReviewFailure:
    # T-5.16
    def test_validate_proposals_invalid_category(self):
        with pytest.raises(SystemExit) as exc_info:
            validate_proposals([_proposal(category="other")])
        assert "category" in _exit_msg(exc_info).lower()

    # T-5.17
    def test_validate_proposals_invalid_slug(self):
        with pytest.raises(SystemExit) as exc_info:
            validate_proposals([_proposal(slug="Bad Slug")])
        assert "slug" in _exit_msg(exc_info).lower()

    # T-5.19
    def test_validate_update_requires_existing_path(self):
        with pytest.raises(SystemExit) as exc_info:
            validate_proposals([_proposal(action="update", existing_path="")])
        msg = _exit_msg(exc_info).lower()
        assert "existing_path" in msg

    # T-5.20
    def test_validate_create_forbids_existing_path(self):
        with pytest.raises(SystemExit) as exc_info:
            validate_proposals([_proposal(action="create", existing_path="wiki/concepts/x.md")])
        msg = _exit_msg(exc_info).lower()
        assert "existing_path" in msg

    # T-5.21
    def test_invalid_action_retries_exhausted(self):
        with patch("builtins.input", side_effect=["shipit"] * 20):
            with pytest.raises(SystemExit) as exc_info:
                review_batch(
                    "gemini",
                    _config(),
                    {"GEMINI_API_KEY": "k"},
                    [_proposal()],
                    "source text",
                    {"source": "note.md"},
                )
        assert "action" in _exit_msg(exc_info).lower()

    # T-5.22
    def test_reject_without_reason_retries_exhausted(self):
        side = ["reject"] + [""] * 20
        with patch("builtins.input", side_effect=side):
            with pytest.raises(SystemExit) as exc_info:
                review_batch(
                    "gemini",
                    _config(),
                    {"GEMINI_API_KEY": "k"},
                    [_proposal()],
                    "source text",
                    {"source": "note.md"},
                )
        assert "reason" in _exit_msg(exc_info).lower()

    # T-5.25
    def test_edit_content_non_zero_exit(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        with patch("src.core.review.subprocess.run", return_value=mock_proc):
            with pytest.raises(SystemExit) as exc_info:
                edit_content("hello", editor_cmd="nano")
        assert "editor" in _exit_msg(exc_info).lower()

    # T-5.26
    def test_edit_content_empty_output(self):
        def _truncate_file(cmd, check):  # noqa: ARG001
            path = cmd[1]
            with open(path, "w", encoding="utf-8") as f:
                f.write("   \n\t")
            proc = MagicMock()
            proc.returncode = 0
            return proc

        with patch("src.core.review.subprocess.run", side_effect=_truncate_file):
            with pytest.raises(SystemExit) as exc_info:
                edit_content("hello", editor_cmd="nano")
        assert "empty" in _exit_msg(exc_info).lower()

    # T-5.27
    def test_repropose_page_failure_propagates(self):
        with patch("src.core.review.complete", side_effect=SystemExit("boom")):
            with pytest.raises(SystemExit) as exc_info:
                repropose_page(
                    "gemini",
                    _config(),
                    {"GEMINI_API_KEY": "k"},
                    _proposal(),
                    "valid reason",
                    "source text",
                    {"source": "note.md"},
                )
        assert "boom" in _exit_msg(exc_info)

    # T-5.30
    def test_validate_batch_size_over_cap(self):
        proposals = [_proposal(slug=f"p-{i}", title=f"Page {i}") for i in range(51)]
        with pytest.raises(SystemExit) as exc_info:
            validate_proposals(proposals)
        msg = _exit_msg(exc_info).lower()
        assert "batch" in msg or "50" in msg

