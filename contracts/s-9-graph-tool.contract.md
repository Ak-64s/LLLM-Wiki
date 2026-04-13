# Contract: S-9 Graph Tool

| Field  | Value |
|--------|-------|
| Slice  | S-9 |
| Date   | 2026-04-12 |
| Status | DRAFT |
| Refs   | AD-12, C-1, C-6, ENGINEERING.md |

---

## APIs

S-9 encapsulates the graph database rendering and caching procedures locally. 

### `build_knowledge_graph(vault_path: str, provider: str, config, env: dict, infer: bool = True) -> dict`

| Aspect | Spec |
|--------|------|
| Module | `src.core.graph` |
| Input | `vault_path`: root workspace directory.<br>`infer`: boolean controlling whether semantic LLM routing generates `INFERRED` links dynamically against cache misses. |
| Output | Serializes output directly to `vault/graph/graph.json` & `vault/graph/graph.html`. Native return supplies structured `dict` summarizing `{ "nodes_processed": int, "cache_hits": int, "inferred_edges": int }`. |
| Raises | Natively catches `ModuleNotFoundError` for missing analytical stacks returning formatted `SystemExit`. Natively bubbles `SystemExit` if dependencies or IO structures collapse unrecoverably. |
| Idempotent | Yes, effectively. It caches execution dynamically via SHA256 meaning repeated structural executions without file modifications will inherently result in zero-latency bypasses. |

---

## HTTP Boundary

If `infer=True`, S-9 utilizes `src.core.llm.complete` sending payloads describing the text of un-cached graph nodes natively seeking linked semantic structures.
- **Provider Matrix**: Identical limits bounded from S-3 abstraction. `4k` API context constraints natively handled chunking.
- **Payload Max Bounds**: LLM evaluates single document texts without iterating full workspace boundaries securely.

---

## Data Structures

The artifact generated maps directly to `vis.js` compatible native JavaScript arrays bound neatly inside JSON.

### `GraphNode`
| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Kebab-case slug natively aligned against title parameters. Primary Key. `Max length: 220 chars` |
| `label` | `str` | Title casing representation. `Max 200 chars`. |
| `group` | `int` | Physical clustering index evaluated via Louvain. Cannot be Null. |
| `hash` | `str` | Base SHA256 string indexing structural payload bounds natively. |

### `GraphEdge`
| Field | Type | Description |
|-------|------|-------------|
| `from` | `str` | Primary key `id` originating semantic connections. |
| `to` | `str` | Target key `id` receiving connection. |
| `type` | `str` | Allowed constants: `EXTRACTED` | `INFERRED` | `AMBIGUOUS`. |
| `confidence` | `float` | Evaluated scalar (`0.0`-`1.0`). `EXTRACTED` natively locks to `1.0`. `INFERRED` bounds `>0.6`. `AMBIGUOUS` falls `>= 0.0, <= 0.6`. |

---

## Boundary Limits

| Boundary | Limit | Rationale |
|----------|-------|-----------|
| NetworkX Render Ceiling | ~1000 nodes natively | Upper bounds of memory allocations computing community layouts locally within synchronous python scopes dynamically. Soft ceiling formally documented L-1 ~300. |
| Re-inference Delay | ~2000ms per un-cached item | Each cache miss requires dedicated single LLM generation payload scaling bounds. |

---

## Tests

Execution Command: `pytest tests/unit/test_s9_graph.py -v`

### Happy Path

| ID | Test | Input | Expected |
|----|------|-------|----------|
| T-9.01 | Structuring Pure Graph | Mock directory omitting cache, forcing structural `EXTRACTED` wikilink resolutions. | `graph.json` correctly constructs array matrix containing elements bridging `EXTRACTED` cleanly without failing boundary bounds natively. |
| T-9.02 | SHA256 Cache Hits | Directory simulating re-execution sequentially maintaining identical `hash` bounds. | System intercepts LLM calling functions returning gracefully mapping pure cache loading outputs resulting in `cache_hits == nodes_processed`. |
| T-9.03 | Semantic Inferences | Simulated cache mismatch on existing physical documents triggering LLM payload queries dynamically generating `[{target_slug: "test", confidence: 0.8}]`. | Edge accurately mapped inside output arrays marked dynamically as `INFERRED`. |
| T-9.04 | HTML Template Insertion | Fully formed `graph.json` executing bounds passing down to `src.core.render`. | Raw Javascript structures appropriately load variables safely formatting `graph.html`. |

### Edge Cases

| ID | Test | Input | Expected |
|----|------|-------|----------|
| T-9.05 | Bookkeeping Ignored | `index.md` & `log.md` structural inclusions cleanly omitted natively. | Index tracking completely skipped from structural evaluations averting mega-clustering issues dynamically safely. |
| T-9.06 | Ambiguous Bounding | Inference generating `{"confidence": 0.4}`. | Edge precisely routed directly natively mapped into the output matrices as `AMBIGUOUS`. |
| T-9.07 | Execution No-Infer | Run parameters blocking inference `infer=False`. | LLM mock completely uncalled regardless of cache miss thresholds resolving nodes efficiently with `EXTRACTED` nodes purely. |

### Failure Cases

| ID | Test | Input | Expected |
|----|------|-------|----------|
| T-9.08 | Dependency Drop | Missing PIP resources (`networkx`). | Application correctly catches python exceptions terminating bounds cleanly using formatted `SystemExit` instructing CLI configurations correctly natively. |
| T-9.09 | Corrupted Json Cache | Random strings filling `graph.json`. | Exception gracefully caught falling back securely to a complete raw full evaluation safely ignoring previous bounds natively throwing warnings. |

---

## Execution Method

### Automated Tests
Run integration paths verifying localized structural generation constraints against caching payloads dynamically:
```bash
pytest tests/unit/test_s9_graph.py -v
```

### Manual Verification
Execute `tools/build_graph.py` interactively confirming interactive graph rendering operations via physical browser inspection outputs:
```bash
python tools/build_graph.py --open
```
