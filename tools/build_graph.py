#!/usr/bin/env python3
"""
CLI entrypoint for LLM Wiki Knowledge Graph generation (S-9).
Usage: python tools/build_graph.py [--no-infer] [--open]
"""

import argparse
import sys
import webbrowser
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.core.config import load_config, load_env
from src.core.provider import ensure_provider_ready
from src.core.graph import build_knowledge_graph

def main() -> None:
    parser = argparse.ArgumentParser(description="Build and render the wiki knowledge graph.")
    parser.add_argument("--no-infer", action="store_true", help="Disable LLM inferences (fast mode).")
    parser.add_argument("--open", action="store_true", help="Launch the graph in system default browser natively.")
    args = parser.parse_args()

    print("\n========================================")
    print("====== [Phase 1] Initialization ======")
    print("========================================\n")
    try:
        config = load_config()
        infer = not args.no_infer
        
        provider = "gemini" # Fallback if inference deactivated
        env = {}
        if infer:
            env = load_env(config.default_provider)
            provider = ensure_provider_ready(config.default_provider, config)
            print(f"Provider '{provider}' is ready for inference mapping.")
        else:
            print("Running in Fast Mode (--no-infer). LLM integrations skipped.")

        print("\n========================================")
        print("======== [Phase 2] Graph Builder =======")
        print("========================================\n")
        
        result = build_knowledge_graph(config.vault_path, provider, config, env, infer=infer)
        
        print(f"Success! Knowledge Graph constructed.")
        print(f" -> Nodes Processed: {result['nodes_processed']}")
        print(f" -> Cache Hits: {result['cache_hits']}")
        print(f" -> Edges Inferred: {result['inferred_edges']}")
        
        html_path = Path(config.vault_path) / "graph" / "graph.html"
        print(f"\nWritten: {html_path.resolve()}")
        
        if args.open:
            print("Opening graph in default browser...")
            webbrowser.open(html_path.resolve().as_uri())
            
    except KeyboardInterrupt:
        print("\nGraph generation cancelled by user.", file=sys.stderr)
        sys.exit(130)
    except SystemExit as e:
        print(f"\n[Fatal Error] {e}", file=sys.stderr)
        sys.exit(e.code)

if __name__ == "__main__":
    main()
