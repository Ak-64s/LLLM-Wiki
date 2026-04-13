#!/usr/bin/env python3
"""
CLI entrypoint for LLM Wiki Read-Only Query Tool (S-10).
Usage: python tools/query.py "question" [--save [path]]
"""

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.core.config import load_config, load_env
from src.core.provider import ensure_provider_ready
from src.core.query import query_wiki

def main() -> None:
    parser = argparse.ArgumentParser(description="Query the LLM Wiki natively utilizing standard semantic bounding routing mechanics.")
    parser.add_argument("question", type=str, help="The formal natural language question to lookup natively.")
    parser.add_argument("--save", nargs="?", const=True, default=False, help="Deferred to Future Phase CLI mapping. Operates globally Read-Only currently.")
    args = parser.parse_args()

    print("\n========================================")
    print("====== [Phase 1] Retrieval Matrix ======")
    print("========================================\n")
    
    if args.save:
        print("[Notice] Query saving disabled for MVP mappings. Running Read-Only.")

    try:
        config = load_config()
        env = load_env(config.default_provider)
        provider = ensure_provider_ready(config.default_provider, config)
        
        print(f"Provider '{provider}' active. Mapping structural layouts internally...\n")

        print("========================================")
        print("======== [Phase 2] Synthesis ===========")
        print("========================================\n")
        
        result = query_wiki(args.question, provider, config, env)
        print(result)
        
        print("\n\n(Query Loop Completed Successfully)")
            
    except KeyboardInterrupt:
        print("\nQuery generation cancelled by user.", file=sys.stderr)
        sys.exit(130)
    except SystemExit as e:
        print(f"\n[Fatal Error] {e}", file=sys.stderr)
        sys.exit(e.code)

if __name__ == "__main__":
    main()
