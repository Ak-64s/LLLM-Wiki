#!/usr/bin/env python3
"""
CLI entrypoint for LLM Wiki Ingestion (S-8.5).
Usage: python tools/ingest.py <source>
"""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path so we can import src
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.core.ingest import execute_ingestion


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a source document into the LLM Wiki.")
    parser.add_argument("source", type=str, help="Path or URL to the source document.")
    
    args = parser.parse_args()

    try:
        execute_ingestion(args.source)
    except KeyboardInterrupt:
        print("\nIngestion cancelled by user.", file=sys.stderr)
        sys.exit(130)
    except SystemExit as e:
        # SystemExit naturally terminates.
        sys.exit(e.code)


if __name__ == "__main__":
    main()
