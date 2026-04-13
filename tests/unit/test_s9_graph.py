"""Tests for S-9 Graph Tool. Contract: contracts/s-9-graph-tool.contract.md"""

import json
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Note: We import the graph module dynamically or handle ImportError natively
# if dependencies are missing. T-9.08 tests that.

@pytest.fixture
def mock_vault(tmp_path):
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    for cat in ("sources", "entities", "concepts"):
        (wiki / cat).mkdir(parents=True)
    
    # Bookkeeping files (T-9.05 should ignore these)
    (wiki / "index.md").write_text("Ignore me", encoding="utf-8")
    (wiki / "log.md").write_text("Ignore me too", encoding="utf-8")

    # Regular files
    (wiki / "concepts" / "ai.md").write_text("Artificial Intelligence uses [[Machine Learning]]", encoding="utf-8")
    (wiki / "concepts" / "machine-learning.md").write_text("ML is cool", encoding="utf-8")
    
    return vault

@pytest.fixture
def mock_config(mock_vault):
    cfg = MagicMock()
    cfg.vault_path = str(mock_vault)
    return cfg

def test_t9_08_dependency_drop(mock_vault, mock_config, monkeypatch):
    """T-9.08: Dependency Drop. Mocks missing networkx."""
    import builtins
    real_import = builtins.__import__
    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'networkx':
            raise ModuleNotFoundError("No module named 'networkx'")
        return real_import(name, globals, locals, fromlist, level)
    
    monkeypatch.setattr(builtins, '__import__', fake_import)
    
    # Reload or import graph
    import sys
    if 'src.core.graph' in sys.modules:
        del sys.modules['src.core.graph']
    
    with pytest.raises(SystemExit) as exc:
        from src.core import graph
        graph.build_knowledge_graph(str(mock_vault), "gemini", mock_config, {}, infer=False)
    assert "Missing dependency:" in str(exc.value)

def test_t9_01_structuring_pure_graph(mock_vault, mock_config):
    """T-9.01: Structuring Pure Graph (EXTRACTED)"""
    from src.core import graph
    
    res = graph.build_knowledge_graph(str(mock_vault), "gemini", mock_config, {}, infer=False)
    assert res["nodes_processed"] == 2
    assert res["inferred_edges"] == 0
    
    graph_json_path = mock_vault / "graph" / "graph.json"
    assert graph_json_path.exists()
    data = json.loads(graph_json_path.read_text())
    
    assert len(data["nodes"]) == 2
    slugs = {n["id"] for n in data["nodes"]}
    assert "ai" in slugs
    assert "machine-learning" in slugs
    
    assert len(data["edges"]) == 1
    edge = data["edges"][0]
    assert edge["from"] == "ai"
    assert edge["to"] == "machine-learning"
    assert edge["type"] == "EXTRACTED"

def test_t9_02_sha256_cache_hits(mock_vault, mock_config, monkeypatch):
    """T-9.02: SHA256 Cache Hits"""
    from src.core import graph
    
    # Run once to build cache
    graph.build_knowledge_graph(str(mock_vault), "gemini", mock_config, {}, infer=False)
    
    # Run again simulating cache hits
    mock_complete = MagicMock()
    monkeypatch.setattr("src.core.graph.complete", mock_complete)
    
    res = graph.build_knowledge_graph(str(mock_vault), "gemini", mock_config, {}, infer=True)
    assert res["cache_hits"] == 2
    assert res["nodes_processed"] == 2
    
    # Since they hit cache, no LLM calls made
    mock_complete.assert_not_called()

def test_t9_03_06_semantic_inferences(mock_vault, mock_config, monkeypatch):
    """T-9.03 & T-9.06: Semantic Inferences and Ambiguous boundaries"""
    from src.core import graph
    
    def fake_complete(prov, cfg, env, sys_prompt, user_prompt):
        if "Artificial Intelligence" in user_prompt:
            return '[{"target_slug": "deep-learning", "confidence": 0.9}]'
        elif "ML is cool" in user_prompt:
             return '[{"target_slug": "stats", "confidence": 0.4}]'
        return '[]'
        
    monkeypatch.setattr("src.core.graph.complete", fake_complete)
    
    res = graph.build_knowledge_graph(str(mock_vault), "gemini", mock_config, {}, infer=True)
    assert res["inferred_edges"] > 0
    
    data = json.loads((mock_vault / "graph" / "graph.json").read_text())
    
    # Count edge types
    inferred = [e for e in data["edges"] if e["type"] == "INFERRED"]
    ambiguous = [e for e in data["edges"] if e["type"] == "AMBIGUOUS"]
    
    assert len(inferred) == 1
    assert inferred[0].get("target_slug") == "deep-learning" or inferred[0].get("to") == "deep-learning"
    assert inferred[0]["confidence"] == 0.9
    
    assert len(ambiguous) == 1
    assert ambiguous[0]["confidence"] == 0.4

def test_t9_04_html_template_insertion(mock_vault, mock_config):
    """T-9.04: HTML Template Insertion"""
    from src.core import graph
    graph.build_knowledge_graph(str(mock_vault), "gemini", mock_config, {}, infer=False)
    
    html_file = mock_vault / "graph" / "graph.html"
    assert html_file.exists()
    content = html_file.read_text()
    assert "vis-network.min.js" in content
    assert "graph.json" in content # or the embedded JSON itself

def test_t9_05_bookkeeping_ignored(mock_vault, mock_config):
    """T-9.05: Bookkeeping Ignored"""
    from src.core import graph
    res = graph.build_knowledge_graph(str(mock_vault), "gemini", mock_config, {}, infer=False)
    data = json.loads((mock_vault / "graph" / "graph.json").read_text())
    
    slugs = {n["id"] for n in data["nodes"]}
    assert "index" not in slugs
    assert "log" not in slugs

def test_t9_07_execution_no_infer(mock_vault, mock_config, monkeypatch):
    """T-9.07: Execution No-Infer"""
    from src.core import graph
    mock_complete = MagicMock()
    monkeypatch.setattr("src.core.graph.complete", mock_complete)
    res = graph.build_knowledge_graph(str(mock_vault), "gemini", mock_config, {}, infer=False)
    
    mock_complete.assert_not_called()

def test_t9_09_corrupted_json_cache(mock_vault, mock_config):
    """T-9.09: Corrupted Json Cache"""
    from src.core import graph
    (mock_vault / "graph").mkdir(exist_ok=True)
    (mock_vault / "graph" / "graph.json").write_text("INVALID JSON #$#$Q$@#")
    
    # Should cleanly ignore and regenerate
    res = graph.build_knowledge_graph(str(mock_vault), "gemini", mock_config, {}, infer=False)
    assert res["nodes_processed"] == 2
    
    # JSON should be repaired
    data = json.loads((mock_vault / "graph" / "graph.json").read_text())
    assert len(data["nodes"]) == 2
