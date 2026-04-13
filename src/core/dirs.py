"""Directory initialization with C-8 validation. Contract: contracts/s-1-foundation.contract.md"""

import os
import sys
from pathlib import Path

from src.core.config import Config

_VAULT_SUBDIRS = [
    os.path.join("wiki", "sources"),
    os.path.join("wiki", "entities"),
    os.path.join("wiki", "concepts"),
    "graph",
]

_SOURCES_SUBDIRS = [
    "articles",
    "pdfs",
    "notes",
]


def ensure_directories(config: Config) -> None:
    vault = Path(config.vault_path).resolve()
    sources = Path(config.sources_path).resolve()

    try:
        common = os.path.commonpath([str(vault), str(sources)])
    except ValueError:
        common = None
    if common is not None and os.path.normcase(common) == os.path.normcase(str(vault)):
        sys.exit(
            f"Sources path '{config.sources_path}' must not be inside "
            f"vault path '{config.vault_path}' (C-8)."
        )

    for subdir in _VAULT_SUBDIRS:
        d = vault / subdir
        existed = d.exists()
        os.makedirs(d, exist_ok=True)
        if not existed:
            print(f"Created: {d}")

    for subdir in _SOURCES_SUBDIRS:
        d = sources / subdir
        existed = d.exists()
        os.makedirs(d, exist_ok=True)
        if not existed:
            print(f"Created: {d}")
