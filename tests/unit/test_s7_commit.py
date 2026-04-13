"""S-7 Commit Layer tests. Contract: contracts/s-7-commit-layer.contract.md"""

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.proposal import PageProposal, Conflict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exit_msg(exc_info) -> str:
    return str(exc_info.value.code) if exc_info.value.code is not None else ""


def _make_config(tmp_path):
    from src.core.config import Config
    return Config(
        vault_path=str(tmp_path),
        sources_path=str(tmp_path / "ext_sources"),
        default_provider="gemini",
        lmstudio_endpoint="http://localhost:1234/v1",
        gemini_model="gemini-3-flash-preview",
        chunk_threshold_lmstudio=4000,
        chunk_threshold_gemini=750000,
        chunk_overlap=200,
    )


def _p(title, slug, category, content, action, existing_path=""):
    return PageProposal(
        title=title, slug=slug, category=category,
        content=content, action=action,
        conflicts=[], existing_path=existing_path,
    )


_META = {"source": "test.txt"}
_TS = "2026-04-12T00:00:00Z"


def _setup_vault(tmp_path):
    wiki = tmp_path / "wiki"
    for cat in ("sources", "entities", "concepts"):
        (wiki / cat).mkdir(parents=True, exist_ok=True)
    return wiki


# ===========================================================================
# Happy Path (T-7.01 through T-7.06)
# ===========================================================================

class TestCommitHappy:

    def test_create_only_batch(self, tmp_path):
        """T-7.01: 3 create proposals → 3 files + index/log updated."""
        from src.core.commit import commit_approved_batch

        _setup_vault(tmp_path)
        config = _make_config(tmp_path)
        approved = [
            _p("Page A", "page-a", "concepts", "Content A.", "create"),
            _p("Page B", "page-b", "entities", "Content B.", "create"),
            _p("Page C", "page-c", "sources", "Content C.", "create"),
        ]

        result = commit_approved_batch(config, approved, _META, committed_at=_TS)

        assert result.page_count == 3
        assert result.created_count == 3
        assert result.updated_count == 0
        assert result.rolled_back is False
        assert (tmp_path / "wiki" / "concepts" / "page-a.md").read_text(encoding="utf-8") == "Content A."
        assert (tmp_path / "wiki" / "entities" / "page-b.md").read_text(encoding="utf-8") == "Content B."
        assert (tmp_path / "wiki" / "sources" / "page-c.md").read_text(encoding="utf-8") == "Content C."
        assert (tmp_path / "wiki" / "index.md").exists()
        assert (tmp_path / "wiki" / "log.md").exists()

    def test_mixed_create_update(self, tmp_path):
        """T-7.02: create + update → correct counts, both persisted."""
        from src.core.commit import commit_approved_batch

        wiki = _setup_vault(tmp_path)
        (wiki / "entities" / "existing.md").write_text("Old content.", encoding="utf-8")

        config = _make_config(tmp_path)
        approved = [
            _p("New Page", "new-page", "concepts", "New.", "create"),
            _p("Existing", "existing", "entities", "Updated.", "update",
               existing_path="wiki/entities/existing.md"),
        ]

        result = commit_approved_batch(config, approved, _META, committed_at=_TS)

        assert result.created_count == 1
        assert result.updated_count == 1
        assert result.page_count == 2
        assert (wiki / "concepts" / "new-page.md").read_text(encoding="utf-8") == "New."
        assert (wiki / "entities" / "existing.md").read_text(encoding="utf-8") == "Updated."

    def test_deterministic_index(self, tmp_path):
        """T-7.03: Same pages on disk → identical index output."""
        from src.core.commit import regenerate_index

        wiki = _setup_vault(tmp_path)
        (wiki / "concepts" / "alpha.md").write_text("Alpha content.", encoding="utf-8")
        (wiki / "entities" / "beta.md").write_text("Beta content.", encoding="utf-8")
        (wiki / "sources" / "gamma.md").write_text("Gamma content.", encoding="utf-8")

        out1 = regenerate_index(str(tmp_path))
        out2 = regenerate_index(str(tmp_path))

        assert out1 == out2
        assert "alpha" in out1
        assert "beta" in out1
        assert "gamma" in out1

    def test_log_entry_append(self, tmp_path):
        """T-7.04: Valid metadata → one new log line with commit info."""
        from src.core.commit import build_log_entry

        line = build_log_entry(
            commit_id="abcdef1234567890",
            source_ref="paper.pdf",
            pages_created=3,
            pages_updated=1,
            committed_at=_TS,
        )

        assert "abcdef1234567890" in line
        assert "paper.pdf" in line
        assert "created=3" in line
        assert "updated=1" in line
        assert _TS in line

    def test_empty_batch(self, tmp_path):
        """T-7.05: Empty approved list → no-op, zero counts."""
        from src.core.commit import commit_approved_batch

        _setup_vault(tmp_path)
        config = _make_config(tmp_path)

        result = commit_approved_batch(config, [], _META, committed_at=_TS)

        assert result.page_count == 0
        assert result.created_count == 0
        assert result.updated_count == 0
        assert result.rolled_back is False

    def test_paths_in_result(self, tmp_path):
        """T-7.06: written_paths, index_path, log_path accurate and inside vault."""
        from src.core.commit import commit_approved_batch

        _setup_vault(tmp_path)
        config = _make_config(tmp_path)
        approved = [_p("Page X", "page-x", "concepts", "Content.", "create")]

        result = commit_approved_batch(config, approved, _META, committed_at=_TS)

        assert len(result.written_paths) == 1
        assert "page-x.md" in result.written_paths[0]
        assert str(tmp_path) in result.index_path
        assert "index.md" in result.index_path
        assert str(tmp_path) in result.log_path
        assert "log.md" in result.log_path
        vault_str = str(tmp_path)
        for wp in result.written_paths:
            assert vault_str in wp


# ===========================================================================
# Edge Cases (T-7.07 through T-7.14)
# ===========================================================================

class TestCommitEdge:

    def test_max_batch_size(self, tmp_path):
        """T-7.07: 50 proposals → valid commit."""
        from src.core.commit import commit_approved_batch

        _setup_vault(tmp_path)
        config = _make_config(tmp_path)
        approved = [
            _p(f"Page {i}", f"page-{i}", "concepts", f"Content {i}.", "create")
            for i in range(50)
        ]

        result = commit_approved_batch(config, approved, _META, committed_at=_TS)

        assert result.page_count == 50
        assert result.created_count == 50

    def test_max_content_size_boundary(self, tmp_path):
        """T-7.08: Content exactly 2,000,000 chars → accepted."""
        from src.core.commit import commit_approved_batch

        _setup_vault(tmp_path)
        config = _make_config(tmp_path)
        content = "x" * 2_000_000
        approved = [_p("Big", "big", "concepts", content, "create")]

        result = commit_approved_batch(config, approved, _META, committed_at=_TS)

        assert result.page_count == 1
        written = (tmp_path / "wiki" / "concepts" / "big.md").read_text(encoding="utf-8")
        assert len(written) == 2_000_000

    def test_existing_file_update(self, tmp_path):
        """T-7.09: Update target exists → file replaced."""
        from src.core.commit import commit_approved_batch

        wiki = _setup_vault(tmp_path)
        target = wiki / "entities" / "target.md"
        target.write_text("Old content before update.", encoding="utf-8")

        config = _make_config(tmp_path)
        approved = [
            _p("Target", "target", "entities", "New content after update.", "update",
               existing_path="wiki/entities/target.md"),
        ]

        result = commit_approved_batch(config, approved, _META, committed_at=_TS)

        assert result.updated_count == 1
        assert target.read_text(encoding="utf-8") == "New content after update."

    def test_missing_category_dirs(self, tmp_path):
        """T-7.10: Category subdirs absent → created before writes."""
        from src.core.commit import commit_approved_batch

        config = _make_config(tmp_path)
        approved = [_p("Page A", "page-a", "concepts", "Content.", "create")]

        result = commit_approved_batch(config, approved, _META, committed_at=_TS)

        assert result.page_count == 1
        assert (tmp_path / "wiki" / "concepts" / "page-a.md").exists()

    def test_run_id_provided(self, tmp_path):
        """T-7.11: Valid 64-char run_id → propagates into log entry."""
        from src.core.commit import commit_approved_batch

        _setup_vault(tmp_path)
        config = _make_config(tmp_path)
        run_id = "a" * 64
        approved = [_p("P", "p", "concepts", "Content.", "create")]

        result = commit_approved_batch(
            config, approved, _META, run_id=run_id, committed_at=_TS,
        )

        log_content = (tmp_path / "wiki" / "log.md").read_text(encoding="utf-8")
        assert run_id in log_content

    def test_committed_at_override(self, tmp_path):
        """T-7.12: Provided timestamp used deterministically in log."""
        from src.core.commit import commit_approved_batch

        _setup_vault(tmp_path)
        config = _make_config(tmp_path)
        ts = "2025-01-15T10:30:00Z"
        approved = [_p("P", "p", "concepts", "Content.", "create")]

        commit_approved_batch(config, approved, _META, committed_at=ts)

        log_content = (tmp_path / "wiki" / "log.md").read_text(encoding="utf-8")
        assert ts in log_content

    def test_non_ascii_content(self, tmp_path):
        """T-7.13: Multilingual content persisted unchanged (UTF-8)."""
        from src.core.commit import commit_approved_batch

        _setup_vault(tmp_path)
        config = _make_config(tmp_path)
        content = "日本語テスト. Ñoño. Ελληνικά."
        approved = [_p("Unicode", "unicode", "concepts", content, "create")]

        commit_approved_batch(config, approved, _META, committed_at=_TS)

        written = (tmp_path / "wiki" / "concepts" / "unicode.md").read_text(encoding="utf-8")
        assert written == content

    def test_duplicate_slugs_diff_categories(self, tmp_path):
        """T-7.14: Same slug in different categories → both valid."""
        from src.core.commit import commit_approved_batch

        _setup_vault(tmp_path)
        config = _make_config(tmp_path)
        approved = [
            _p("Foo Source", "foo", "sources", "Source content.", "create"),
            _p("Foo Concept", "foo", "concepts", "Concept content.", "create"),
        ]

        result = commit_approved_batch(config, approved, _META, committed_at=_TS)

        assert result.page_count == 2
        assert (tmp_path / "wiki" / "sources" / "foo.md").exists()
        assert (tmp_path / "wiki" / "concepts" / "foo.md").exists()


# ===========================================================================
# Failure: Validation (T-7.15 through T-7.24, T-7.29, T-7.30)
# ===========================================================================

class TestCommitValidation:

    def test_invalid_category(self):
        """T-7.15: Category not in enum → SystemExit naming field."""
        from src.core.commit import validate_commit_payload

        approved = [_p("P", "p", "invalid-cat", "Content.", "create")]
        with pytest.raises(SystemExit) as exc_info:
            validate_commit_payload(approved, _META)
        assert "category" in _exit_msg(exc_info).lower()

    def test_invalid_slug_regex(self):
        """T-7.16: Slug with uppercase/space/special → SystemExit."""
        from src.core.commit import validate_commit_payload

        approved = [_p("P", "INVALID slug!", "concepts", "Content.", "create")]
        with pytest.raises(SystemExit) as exc_info:
            validate_commit_payload(approved, _META)
        assert "slug" in _exit_msg(exc_info).lower()

    def test_empty_content(self):
        """T-7.17: Whitespace-only content → SystemExit."""
        from src.core.commit import validate_commit_payload

        approved = [_p("P", "p", "concepts", "   ", "create")]
        with pytest.raises(SystemExit) as exc_info:
            validate_commit_payload(approved, _META)
        assert "content" in _exit_msg(exc_info).lower()

    def test_update_missing_existing_path(self):
        """T-7.18: Update with empty existing_path → SystemExit."""
        from src.core.commit import validate_commit_payload

        approved = [_p("P", "p", "concepts", "Content.", "update", existing_path="")]
        with pytest.raises(SystemExit) as exc_info:
            validate_commit_payload(approved, _META)
        assert "existing_path" in _exit_msg(exc_info).lower()

    def test_create_with_existing_path(self):
        """T-7.19: Create with non-empty existing_path → SystemExit."""
        from src.core.commit import validate_commit_payload

        approved = [_p("P", "p", "concepts", "Content.", "create",
                        existing_path="wiki/foo.md")]
        with pytest.raises(SystemExit) as exc_info:
            validate_commit_payload(approved, _META)
        assert "existing_path" in _exit_msg(exc_info).lower()

    def test_duplicate_target_paths(self):
        """T-7.20: Two proposals → same category/slug → SystemExit."""
        from src.core.commit import validate_commit_payload

        approved = [
            _p("A", "same", "concepts", "Content A.", "create"),
            _p("B", "same", "concepts", "Content B.", "create"),
        ]
        with pytest.raises(SystemExit) as exc_info:
            validate_commit_payload(approved, _META)
        assert "duplicate" in _exit_msg(exc_info).lower()

    def test_path_traversal_slug(self):
        """T-7.21: Slug with path traversal chars → SystemExit."""
        from src.core.commit import validate_commit_payload

        approved = [_p("Evil", "foo/../bar", "concepts", "Content.", "create")]
        with pytest.raises(SystemExit) as exc_info:
            validate_commit_payload(approved, _META)
        assert "slug" in _exit_msg(exc_info).lower()

    def test_invalid_source_meta_type(self):
        """T-7.22: source_meta not dict → SystemExit."""
        from src.core.commit import validate_commit_payload

        with pytest.raises(SystemExit) as exc_info:
            validate_commit_payload([], "not-a-dict")
        assert "source_meta" in _exit_msg(exc_info).lower()

    def test_missing_source_key(self):
        """T-7.23: source_meta missing 'source' key → SystemExit."""
        from src.core.commit import validate_commit_payload

        with pytest.raises(SystemExit) as exc_info:
            validate_commit_payload([], {})
        assert "source" in _exit_msg(exc_info).lower()

    def test_invalid_committed_at(self, tmp_path):
        """T-7.24: Non-UTC timestamp → SystemExit."""
        from src.core.commit import commit_approved_batch

        _setup_vault(tmp_path)
        config = _make_config(tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            commit_approved_batch(
                config, [], _META, committed_at="2026-04-12 14:30:00",
            )
        assert "committed_at" in _exit_msg(exc_info).lower()

    def test_oversized_aggregate(self):
        """T-7.29: Aggregate content >20M chars → SystemExit."""
        from src.core.commit import validate_commit_payload

        approved = [
            _p(f"P{i}", f"p{i}", "concepts", "x" * 2_000_000, "create")
            for i in range(11)
        ]
        with pytest.raises(SystemExit) as exc_info:
            validate_commit_payload(approved, _META)
        assert "aggregate" in _exit_msg(exc_info).lower()

    def test_invalid_run_id_format(self):
        """T-7.30: run_id with disallowed chars → SystemExit."""
        from src.core.commit import validate_commit_payload

        approved = [_p("P", "p", "concepts", "Content.", "create")]
        with pytest.raises(SystemExit) as exc_info:
            validate_commit_payload(approved, _META, run_id="invalid chars!@#")
        assert "run_id" in _exit_msg(exc_info).lower()


# ===========================================================================
# Failure: Rollback (T-7.25 through T-7.28)
# ===========================================================================

class TestCommitRollback:

    def test_mid_page_write_failure(self, tmp_path):
        """T-7.25: Write fails on 2nd page → all touched files restored."""
        from src.core.commit import commit_approved_batch

        _setup_vault(tmp_path)
        config = _make_config(tmp_path)
        approved = [
            _p("Page A", "page-a", "concepts", "Content A.", "create"),
            _p("Page B", "page-b", "concepts", "Content B.", "create"),
        ]

        fail_target = (tmp_path / "wiki" / "concepts" / "page-b.md").resolve()
        original_write_text = Path.write_text

        def failing_write(self_path, *args, **kwargs):
            if self_path.resolve() == fail_target:
                raise OSError("disk full")
            return original_write_text(self_path, *args, **kwargs)

        with patch.object(Path, "write_text", failing_write):
            with pytest.raises(SystemExit) as exc_info:
                commit_approved_batch(config, approved, _META, committed_at=_TS)

        assert not (tmp_path / "wiki" / "concepts" / "page-a.md").exists()
        assert not (tmp_path / "wiki" / "concepts" / "page-b.md").exists()
        assert "rolled back" in _exit_msg(exc_info).lower()

    def test_index_write_failure(self, tmp_path):
        """T-7.26: Index write fails → pages restored to pre-state."""
        from src.core.commit import commit_approved_batch

        _setup_vault(tmp_path)
        config = _make_config(tmp_path)
        approved = [_p("Page A", "page-a", "concepts", "Content A.", "create")]

        fail_target = (tmp_path / "wiki" / "index.md").resolve()
        original_write_text = Path.write_text

        def failing_write(self_path, *args, **kwargs):
            if self_path.resolve() == fail_target:
                raise OSError("index write failed")
            return original_write_text(self_path, *args, **kwargs)

        with patch.object(Path, "write_text", failing_write):
            with pytest.raises(SystemExit):
                commit_approved_batch(config, approved, _META, committed_at=_TS)

        assert not (tmp_path / "wiki" / "concepts" / "page-a.md").exists()

    def test_log_write_failure(self, tmp_path):
        """T-7.27: Log write fails → pages + index restored."""
        from src.core.commit import commit_approved_batch

        _setup_vault(tmp_path)
        config = _make_config(tmp_path)
        approved = [_p("Page A", "page-a", "concepts", "Content A.", "create")]

        fail_target = (tmp_path / "wiki" / "log.md").resolve()
        original_write_text = Path.write_text

        def failing_write(self_path, *args, **kwargs):
            if self_path.resolve() == fail_target:
                raise OSError("log write failed")
            return original_write_text(self_path, *args, **kwargs)

        with patch.object(Path, "write_text", failing_write):
            with pytest.raises(SystemExit):
                commit_approved_batch(config, approved, _META, committed_at=_TS)

        assert not (tmp_path / "wiki" / "concepts" / "page-a.md").exists()
        assert not (tmp_path / "wiki" / "index.md").exists()

    def test_rollback_failure_surfaced(self, tmp_path):
        """T-7.28: Write + rollback both fail → SystemExit with rollback context."""
        from src.core.commit import commit_approved_batch

        _setup_vault(tmp_path)
        config = _make_config(tmp_path)
        approved = [
            _p("Page A", "page-a", "concepts", "Content A.", "create"),
            _p("Page B", "page-b", "concepts", "Content B.", "create"),
        ]

        fail_target = (tmp_path / "wiki" / "concepts" / "page-b.md").resolve()
        original_write_text = Path.write_text
        original_unlink = Path.unlink

        def failing_write(self_path, *args, **kwargs):
            if self_path.resolve() == fail_target:
                raise OSError("disk full")
            return original_write_text(self_path, *args, **kwargs)

        def failing_unlink(self_path, *args, **kwargs):
            raise OSError("permission denied")

        with patch.object(Path, "write_text", failing_write):
            with patch.object(Path, "unlink", failing_unlink):
                with pytest.raises(SystemExit) as exc_info:
                    commit_approved_batch(config, approved, _META, committed_at=_TS)

        msg = _exit_msg(exc_info).lower()
        assert "rollback" in msg
