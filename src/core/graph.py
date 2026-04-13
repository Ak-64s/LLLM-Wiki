"""Knowledge Graph generator. Contract: contracts/s-9-graph-tool.contract.md"""

import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import networkx as nx
    from community import best_partition
except ImportError as e:
    sys.exit(f"Missing dependency: {e.name}. Install with: pip install networkx python-louvain")

from src.core.llm import complete
from src.core.proposal import slugify

_LINK_REGEX = re.compile(r"\[\[([^\]]+)\]\]")

_SYSTEM_PROMPT = """\
You are a knowledge graph edge extractor.
Analyze this text and output implicit semantic relationships to other concepts.
Return ONLY a JSON array.
Format: [{"target_slug": "concept-name", "confidence": 0.85}]
Confidence is a float between 0.0 and 1.0. Do not wrap in markdown blocks, just return JSON array.
"""


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_cache(graph_json_path: Path) -> dict:
    if not graph_json_path.exists():
        return {}
    try:
        data = json.loads(graph_json_path.read_text(encoding="utf-8"))
        # Return a map of slug -> hash
        return {n["id"]: n["hash"] for n in data.get("nodes", []) if "id" in n and "hash" in n}
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Corrupted graph.json: {e}. Rebuilding from scratch.")
        return {}


def _infer_edges(provider: str, config, env: dict, text: str) -> list[dict]:
    raw = complete(provider, config, env, _SYSTEM_PROMPT, text)
    raw = raw.strip()
    raw = re.compile(r"^```(?:json)?\s*\n?", re.MULTILINE).sub("", raw)
    raw = re.compile(r"\n?```\s*$", re.MULTILINE).sub("", raw)
    
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1:
        raw = raw[start:end+1]
        
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        out = []
        for d in data:
            if isinstance(d, dict) and "target_slug" in d and "confidence" in d:
                out.append(d)
        return out
    except json.JSONDecodeError as e:
        logger.warning(f"LLM JSON format error: {e}. Raw payload: {raw}")
        return []


def _generate_html(graph_json_path: Path, html_path: Path) -> None:
    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <title>LLM Wiki Knowledge Graph</title>
  <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <style type="text/css">
    #mynetwork {{ width: 100vw; height: 100vh; border: 1px solid lightgray; }}
    body {{ margin: 0; padding: 0; }}
  </style>
</head>
<body>
<div id="mynetwork"></div>
<script type="text/javascript">
  fetch('graph.json').then(r => r.json()).then(data => {{
    var nodes = new vis.DataSet(data.nodes);
    var edges = new vis.DataSet(data.edges);
    var container = document.getElementById('mynetwork');
    var graphData = {{ nodes: nodes, edges: edges }};
    var options = {{
      nodes: {{ shape: 'dot', size: 16 }},
      physics: {{ forceAtlas2Based: {{ gravitationalConstant: -26, centralGravity: 0.005, springLength: 230, springConstant: 0.18 }}, maxVelocity: 146, solver: 'forceAtlas2Based', timestep: 0.35, stabilization: {{ iterations: 150 }} }}
    }};
    var network = new vis.Network(container, graphData, options);
  }}).catch(err => console.error("Could not load graph.json", err));
</script>
</body>
</html>
"""
    html_path.write_text(html_content, encoding="utf-8")


def build_knowledge_graph(vault_path: str, provider: str, config, env: dict, infer: bool = True) -> dict:
    wiki_path = Path(vault_path) / "wiki"
    graph_dir = Path(vault_path) / "graph"
    graph_dir.mkdir(exist_ok=True, parents=True)
    
    graph_json_path = graph_dir / "graph.json"
    html_path = graph_dir / "graph.html"
    
    cache = _load_cache(graph_json_path)
    
    # Existing data from cache to carry over INFERRED edges if the content didn't change
    cached_graph = {"nodes": [], "edges": []}
    if graph_json_path.exists():
        try:
            cached_graph = json.loads(graph_json_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to load cached graph for implicit edges: {e}")

    cached_inferred_edges = [e for e in cached_graph.get("edges", []) if e.get("type") in ("INFERRED", "AMBIGUOUS")]
    
    G = nx.Graph()
    
    nodes_data = {}
    edges_data = [] # List of tuples: (source, target, type, confidence)
    
    cache_hits = 0
    inferred_count = 0
    
    for category in ("sources", "entities", "concepts"):
        cat_dir = wiki_path / category
        if not cat_dir.exists():
            continue
            
        for filepath in cat_dir.glob("*.md"):
            slug = filepath.stem
            if slug in ("index", "log"): # T-9.05 constraint
                continue
                
            content = filepath.read_text(encoding="utf-8")
            h = _hash_content(content)
            
            nodes_data[slug] = {
                "id": slug,
                "label": slug.replace("-", " ").title(),
                "hash": h
            }
            G.add_node(slug)
            
            # Step 1: EXTRACTED edges
            links = _LINK_REGEX.findall(content)
            for link in links:
                target = slugify(link)
                edges_data.append((slug, target, "EXTRACTED", 1.0))
            
            # Step 2: INFERRED / AMBIGUOUS edges
            if infer:
                if slug in cache and cache[slug] == h:
                    cache_hits += 1
                    # Carry over previous inferred edges
                    for ce in cached_inferred_edges:
                        if ce.get("from") == slug:
                            edges_data.append((ce["from"], ce["to"], ce["type"], ce["confidence"]))
                            inferred_count += 1
                else:
                    # Cache miss -> Prompt LLM
                    semantic_edges = _infer_edges(provider, config, env, content)
                    for edge in semantic_edges:
                        t = edge.get("target_slug") or edge.get("to") # Handle API variations flexibly
                        c = float(edge.get("confidence", 0.0))
                        if not t: continue
                        
                        target_slug = slugify(t)
                        typ = "INFERRED" if c > 0.6 else "AMBIGUOUS"
                        edges_data.append((slug, target_slug, typ, c))
                        inferred_count += 1
    
    # Filter out ghost nodes (targets that don't physically exist in the graph)
    valid_edges = []
    for source, target, typ, conf in edges_data:
        if source in nodes_data and target in nodes_data:
            valid_edges.append((source, target, typ, conf))
    edges_data = valid_edges

    # Step 3: Insert edges into NetworkX
    for source, target, typ, conf in edges_data:
        G.add_edge(source, target) # Unweighted for Louvain, or could use conf as weight
        
    # Step 4: Louvain communities
    # Handle single isolated nodes cleanly without failing
    if len(G.nodes) > 0:
        if len(G.edges) > 0:
            partitions = best_partition(G)
        else:
            partitions = {n: 0 for n in G.nodes}
    else:
        partitions = {}
        
    # Step 5: Serialize JSON
    final_nodes = []
    for slug, n_data in nodes_data.items():
        n_data["group"] = partitions.get(slug, 0)
        final_nodes.append(n_data)
        
    final_edges = []
    for source, target, typ, conf in edges_data:
        final_edges.append({
            "from": source,
            "to": target,
            "type": typ,
            "confidence": conf
        })
        
    payload = {
        "nodes": final_nodes,
        "edges": final_edges
    }
    
    # Atomic write to prevent cache corruption
    tmp_path = graph_json_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp_path, graph_json_path)
    _generate_html(graph_json_path, html_path)
    
    return {
        "nodes_processed": len(nodes_data),
        "cache_hits": cache_hits,
        "inferred_edges": inferred_count
    }
