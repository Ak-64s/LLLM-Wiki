import os
import sys
from pathlib import Path

import pytest

from src.core.lint import (
    LintIssue,
    LintReport,
    check_broken_links,
    check_duplicate_slugs,
    check_empty_pages,
    check_index_staleness,
    check_orphans,
    format_report,
    run_all_checks,
)


def create_vault(tmp_path: Path):
    vault = tmp_path / "vault" / "wiki"
    for cat in ["sources", "entities", "concepts"]:
        (vault / cat).mkdir(parents=True, exist_ok=True)
    return vault


def write_file(vault: Path, path: str, content: str):
    p = vault / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_t8_01_clean_wiki(tmp_path):
    vault = create_vault(tmp_path)
    # A properly cross-linked synthetic vault
    write_file(vault, "index.md", "Index\n[[Source 1]]\n[[Source 2]]")
    write_file(vault, "sources/source-1.md", "This is source 1. Lots of meaningful text here. Blah blah blah blah blah blah.\n[[Source 2]]")
    write_file(vault, "concepts/source-2.md", "This is source 2. Also lots of meaningful text so it passes the empty test. Blah blah blah.\n[[Source 1]]")
    
    report = run_all_checks(str(vault.parent))
    assert report.total_issues == 0, format_report(report)
    assert len(report.issues) == 0


def test_t8_03_exclusion_list_integrity(tmp_path):
    vault = create_vault(tmp_path)
    # Bookkeeping files that have < 50 chars or are orphans shouldn't be flagged.
    write_file(vault, "index.md", "[[Source 1]]")
    write_file(vault, "log.md", "")
    write_file(vault, "overview.md", "tiny")
    write_file(vault, "lint-report.md", "also tiny")
    
    # We need at least one valid file, otherwise index staleness flags Source 1
    write_file(vault, "sources/source-1.md", "Valid content here that goes on for enough characters to bypass the empty check. Yes it does.")
    
    report = run_all_checks(str(vault.parent))
    # Still 0 issues for bookkeeping files. source-1.md will naturally be an orphan, which is fine.
    for issue in report.issues:
        assert "log.md" not in issue.file_path
        assert "overview.md" not in issue.file_path
        assert "lint-report.md" not in issue.file_path
        # index.md might be flagged if stale, let's just make sure it's not orphan or empty_page
        if "index.md" in issue.file_path:
            assert issue.check_type == "stale_index"


def test_t8_04_content_with_frontmatter(tmp_path):
    vault = create_vault(tmp_path)
    # Long frontmatter, empty body
    content = "---\ntitle: Long frontmatter\ndate: 2026-04-12\nmetadata: going on and on and on and on\nsome_other_field: really filling up characters to trick the parser\n---\n\n  \n"
    write_file(vault, "sources/frontmatter-only.md", content)
    write_file(vault, "index.md", "[[Frontmatter Only]]")
    
    # It has 0 inbound links (except index), so it's also an orphan.
    # We want to check empty page. Let's give it an inbound link so it's not an orphan.
    write_file(vault, "concepts/other.md", "Valid content here that is very long enough. [[Frontmatter Only]]")
    write_file(vault, "index.md", "[[Frontmatter Only]]\n[[Other]]")
    
    report = run_all_checks(str(vault.parent))
    
    empty_issues = [iss for iss in report.issues if iss.check_type == "empty_page"]
    assert len(empty_issues) == 1
    assert "frontmatter-only.md" in empty_issues[0].file_path


def test_t8_05_orphaned_page_detection(tmp_path):
    vault = create_vault(tmp_path)
    # Page with 0 inbound wikilinks
    write_file(vault, "sources/isolate.md", "This is an isolated page and it has a bunch of text so not empty.")
    write_file(vault, "index.md", "[[Isolate]]")  # index links it, but that shouldn't save it!
    
    report = run_all_checks(str(vault.parent))
    orphans = [i for i in report.issues if i.check_type == "orphan"]
    assert len(orphans) == 1
    assert "isolate.md" in orphans[0].file_path


def test_t8_06_broken_link_detection(tmp_path):
    vault = create_vault(tmp_path)
    write_file(vault, "sources/page-1.md", "Valid text here that is 50 chars exactly. Yes it is.... [[Nonexistent]]")
    write_file(vault, "index.md", "[[Page 1]]")
    
    report = run_all_checks(str(vault.parent))
    broken = [i for i in report.issues if i.check_type == "broken_link"]
    assert len(broken) == 1
    # Check that it cites the source file
    assert "page-1.md" in broken[0].file_path
    assert "nonexistent" in broken[0].details.lower() or "Nonexistent" in broken[0].details


def test_t8_07_duplicate_slug_cross_category(tmp_path):
    vault = create_vault(tmp_path)
    write_file(vault, "sources/foo.md", "Fifty characters of text here. I will just type out enough words.")
    write_file(vault, "concepts/foo.md", "Fifty characters of text here. I will just type out enough words.")
    # To avoid orphans, link them to each other
    write_file(vault, "sources/foo.md", "Fifty characters of text here. I will just type out enough words. [[Foo]]")
    write_file(vault, "concepts/foo.md", "Fifty characters of text here. I will just type out enough words. [[Foo]]")
    write_file(vault, "index.md", "[[Foo]]")
    
    report = run_all_checks(str(vault.parent))
    dups = [i for i in report.issues if i.check_type == "duplicate_slug"]
    # Usually you report 1 issue per collision, or 1 issue per file. Contract says:
    # "2 duplicate_slug issues" expected.
    assert len(dups) == 2
    paths = [d.file_path for d in dups]
    assert any("sources/foo.md" in p or "sources\\foo.md" in p for p in paths)
    assert any("concepts/foo.md" in p or "concepts\\foo.md" in p for p in paths)


def test_t8_08_blank_or_whitespace_user_page(tmp_path):
    vault = create_vault(tmp_path)
    write_file(vault, "sources/blank.md", "   \n\t  ")
    write_file(vault, "index.md", "[[Blank]]")
    
    report = run_all_checks(str(vault.parent))
    empty = [i for i in report.issues if i.check_type == "empty_page"]
    assert len(empty) == 1
    assert "blank.md" in empty[0].file_path


def test_t8_09_stale_index_detection_missing(tmp_path):
    vault = create_vault(tmp_path)
    # File on disk, but not in index
    write_file(vault, "sources/actual-file.md", "Fifty characters of text here. I will just type out enough words.")
    # It will also be an orphan, but we focus on index staleness.
    write_file(vault, "index.md", "Index is empty")
    
    report = run_all_checks(str(vault.parent))
    stale = [i for i in report.issues if i.check_type == "stale_index"]
    assert len(stale) == 1
    assert "actual-file.md" in stale[0].details or "actual-file" in stale[0].details


def test_t8_09_stale_index_detection_stale_entry(tmp_path):
    vault = create_vault(tmp_path)
    # Entry in index, no file on disk
    write_file(vault, "index.md", "[[Deleted File]]")
    
    report = run_all_checks(str(vault.parent))
    stale = [i for i in report.issues if i.check_type == "stale_index"]
    assert len(stale) == 1
    assert "deleted-file" in stale[0].details.lower() or "Deleted File" in stale[0].details


def test_t8_10_missing_vault(tmp_path):
    with pytest.raises(SystemExit):
        run_all_checks(str(tmp_path / "does_not_exist"))


# Contract: "T-8.02 --save flag persistence"
def test_t8_02_cli_save(tmp_path, monkeypatch):
    vault = create_vault(tmp_path)
    # Provide one issue so report is non-empty
    write_file(vault, "sources/orphan-page.md", "This is an orphaned page with fifty chars of text.")
    write_file(vault, "index.md", "[[Orphan Page]]")
    
    # Needs a config file to set vault path for CLI
    config_path = tmp_path / "config.json"
    import json
    config_path.write_text(json.dumps({
        "vault_path": str(vault.parent),
        "sources_path": str(tmp_path / "sources")
    }))
    
    import tools.lint
    
    # Mock sys.argv
    monkeypatch.setattr(sys, "argv", ["lint.py", "--save"])
    # Mock config loader to read this temporary config
    from src.core import lint
    def mock_load_config(*args, **kwargs):
        from src.core.config import Config
        return Config(vault_path=str(vault.parent), sources_path="")
    
    monkeypatch.setattr(tools.lint, "load_config", mock_load_config)
    
    # The normal script outputs to stdout, which we can ignore, but it should create lint-report.md
    tools.lint.main()
    
    report_file = vault / "lint-report.md"
    assert report_file.exists()
    content = report_file.read_text("utf-8")
    assert "orphan" in content.lower()
    
    # Also test that it doesn't fail if wiki is clean
    # Remove the orphan and the stale index entry
    (vault / "sources/orphan-page.md").unlink()
    (vault / "index.md").write_text("Index", encoding="utf-8")
    tools.lint.main()
    content = report_file.read_text("utf-8")
    assert "no issues found" in content.lower()
