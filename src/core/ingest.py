"""S-8.5 Ingest CLI Orchestration"""

import sys

from src.core.config import load_config, load_env
from src.core.provider import ensure_provider_ready
from src.core.extract import extract_source
from src.core.batch import generate_batch
from src.core.review import review_batch
from src.core.propagate import propagate_edits
from src.core.commit import commit_approved_batch


def _print_phase(name: str) -> None:
    print(f"\n{'='*40}")
    print(f" {name} ".center(40, "="))
    print(f"{'='*40}\n")


def execute_ingestion(source: str) -> None:
    _print_phase("[Phase 1] Initialization")
    try:
        config = load_config()
        env = load_env(config.default_provider)
        
        provider = ensure_provider_ready(config.default_provider, config)
        print(f"Provider '{provider}' is ready.")
        
        _print_phase("[Phase 2] Extraction")
        print(f"Extracting source: {source}")
        source_text, source_meta = extract_source(source)
        print(f"Extracted {len(source_text)} characters.")
        
        _print_phase("[Phase 3] Generating Batch")
        print("Analyzing text and planning pages...")
        proposals = generate_batch(provider, config, env, source_text, source_meta)
        if not proposals:
            print("No pages proposed.")
            return

        print(f"{len(proposals)} pages proposed.")

        _print_phase("[Phase 4] Review Loop")
        
        def _on_edit(edited_title: str, edited_content: str, remaining_pending: list) -> list:
            if not remaining_pending:
                return remaining_pending
            
            print(f"\n[Edit Propagation] Checking {len(remaining_pending)} downstream pages for impact...")
            updated_pending = propagate_edits(
                edited_title, edited_content, remaining_pending,
                provider, config, env, source_text, source_meta
            )
            return updated_pending

        approved = review_batch(
            provider=provider,
            config=config,
            env=env,
            proposals=proposals,
            source_text=source_text,
            source_meta=source_meta,
            on_edit_callback=_on_edit
        )

        if not approved:
            print("No pages approved for commit.")
            return

        _print_phase("[Phase 5] Commit")
        print(f"Committing {len(approved)} approved pages...")
        result = commit_approved_batch(config, approved, source_meta)
        
        print(f"Success! Commit ID: {result.commit_id}")
        print(f"Pages written: {result.page_count} ({result.created_count} created, {result.updated_count} updated).")

    except SystemExit as sys_exit:
        # Gracefully handle failures propagated natively from underlying modules
        print(f"\n[Fatal Error] {sys_exit}", file=sys.stderr)
        raise
