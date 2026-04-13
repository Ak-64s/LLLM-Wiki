import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

from src.core.proposal import slugify

_EXCLUDED_FILES = {"index.md", "log.md", "overview.md", "lint-report.md"}
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass
class LintIssue:
    check_type: str
    file_path: str
    details: str


@dataclass
class LintReport:
    total_issues: int
    issues: List[LintIssue]
    duration_ms: int


def _fail(msg: str) -> None:
    sys.exit(msg)


def _get_files(vault_wiki: Path) -> List[Path]:
    files = []
    if not vault_wiki.exists():
        _fail(f"Wiki directory does not exist: {vault_wiki}")
    for cat in ["sources", "entities", "concepts"]:
        d = vault_wiki / cat
        if d.exists():
            for p in d.rglob("*.md"):
                if p.is_file() and p.name not in _EXCLUDED_FILES:
                    files.append(p)
    return files


def check_orphans(vault_wiki: Path, actual_files: List[Path]) -> List[LintIssue]:
    issues = []
    target_slugs = set()
    for f in actual_files:
        text = f.read_text(encoding="utf-8")
        targets = _WIKILINK_RE.findall(text)
        for t in targets:
            try:
                target_slugs.add(slugify(t))
            except ValueError:
                pass

    for f in actual_files:
        if f.stem not in target_slugs:
            issues.append(LintIssue(
                check_type="orphan",
                file_path=f.relative_to(vault_wiki).as_posix(),
                details="Page has 0 inbound wikilinks.",
            ))
    return issues


def check_broken_links(vault_wiki: Path, actual_files: List[Path]) -> List[LintIssue]:
    issues = []
    actual_slugs = {f.stem for f in actual_files}
    for f in actual_files:
        text = f.read_text(encoding="utf-8")
        targets = _WIKILINK_RE.findall(text)
        for t in targets:
            try:
                s = slugify(t)
                if s not in actual_slugs:
                    issues.append(LintIssue(
                        check_type="broken_link",
                        file_path=f.relative_to(vault_wiki).as_posix(),
                        details=f"Target page '{t}' (slug: {s}) does not exist."
                    ))
            except ValueError:
                pass
    return issues


def check_duplicate_slugs(vault_wiki: Path, actual_files: List[Path]) -> List[LintIssue]:
    issues = []
    slug_to_paths = {}
    for f in actual_files:
        slug_to_paths.setdefault(f.stem, []).append(f)

    for slug, paths in slug_to_paths.items():
        if len(paths) > 1:
            for p in paths:
                issues.append(LintIssue(
                    check_type="duplicate_slug",
                    file_path=p.relative_to(vault_wiki).as_posix(),
                    details=f"Duplicate slug '{slug}' shared by {len(paths)} files."
                ))
    return issues


def check_empty_pages(vault_wiki: Path, actual_files: List[Path]) -> List[LintIssue]:
    issues = []
    for f in actual_files:
        text = f.read_text(encoding="utf-8")
        # Remove frontmatter if present
        text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.DOTALL)
        # Count non-whitespace
        non_ws = len(re.sub(r"\s", "", text))
        if non_ws < 50:
            issues.append(LintIssue(
                check_type="empty_page",
                file_path=f.relative_to(vault_wiki).as_posix(),
                details=f"Page body has {non_ws} non-whitespace characters (threshold is 50)."
            ))
    return issues


def check_index_staleness(vault_wiki: Path, actual_files: List[Path]) -> List[LintIssue]:
    issues = []
    index_file = vault_wiki / "index.md"
    index_slugs = set()
    if index_file.exists():
        text = index_file.read_text(encoding="utf-8")
        targets = _WIKILINK_RE.findall(text)
        for t in targets:
            try:
                index_slugs.add(slugify(t))
            except ValueError:
                pass

    actual_slugs = {}
    for f in actual_files:
        actual_slugs[f.stem] = f

    # Missing entries
    for stem, f in actual_slugs.items():
        if stem not in index_slugs:
            issues.append(LintIssue(
                check_type="stale_index",
                file_path="index.md",
                details=f"Missing entry: File '{f.relative_to(vault_wiki).as_posix()}' exists on disk but is not linked in index."
            ))

    # Stale entries
    for s in index_slugs:
        if s not in actual_slugs:
            issues.append(LintIssue(
                check_type="stale_index",
                file_path="index.md",
                details=f"Stale entry: index.md links to slug '{s}' but no such file exists."
            ))

    return issues


def run_all_checks(vault_path: str) -> LintReport:
    t0 = time.time()
    vault_p = Path(vault_path)
    if not vault_p.exists():
        _fail(f"Vault path does not exist: {vault_path}")
    
    vault_wiki = vault_p / "wiki"
    
    actual_files = _get_files(vault_wiki)
    issues = []

    issues.extend(check_orphans(vault_wiki, actual_files))
    issues.extend(check_broken_links(vault_wiki, actual_files))
    issues.extend(check_duplicate_slugs(vault_wiki, actual_files))
    issues.extend(check_empty_pages(vault_wiki, actual_files))
    issues.extend(check_index_staleness(vault_wiki, actual_files))

    dt = int((time.time() - t0) * 1000)
    return LintReport(
        total_issues=len(issues),
        issues=issues,
        duration_ms=dt
    )


def format_report(report: LintReport) -> str:
    if report.total_issues == 0:
        return "No issues found."

    out = [f"# Lint Report\n\nTotal issues: {report.total_issues}\nRun time: {report.duration_ms}ms\n"]

    by_type = {}
    for iss in report.issues:
        by_type.setdefault(iss.check_type, []).append(iss)

    for ct in sorted(by_type.keys()):
        out.append(f"## {ct.title().replace('_', ' ')}\n")
        items = sorted(by_type[ct], key=lambda x: x.file_path)
        for iss in items:
            out.append(f"- **{iss.file_path}**: {iss.details}")
        out.append("")

    return "\n".join(out).strip()
