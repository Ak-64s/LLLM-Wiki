# S-9 Graph Tool — Pre-Implementation ADR

## Goal
Construct `tools/build_graph.py` establishing an interactive physical knowledge graph bridging both deterministic structural connections and semantic AI-inferred relationships across the wiki.

## Systems Touched
- `tools/build_graph.py` — The CLI executor capturing `--no-infer` and `--open`.
- `src/core/graph.py` — Dedicated logic wrapping `NetworkX`, managing SHA256 hashing arrays, executing `python-louvain` community detection, and generating the `graph.json` artifacts.
- `src/core/render.py` (or integrated in graph.py) — Logic injecting `graph.json` directly into an offline HTML string utilizing `vis.js`.
- `vault/graph/` — Physical directory storing outputs.

## Assumptions
- `index.md` and `log.md` must be inherently stripped from the graph calculation loop since they contain bookkeeping relationships that will structurally corrupt Louvain's community classification algorithms (forcing everything into a single macro topic).
- Inferred edges scale poorly. We must strictly index the SHA256 hash of each page's text into `graph.json` and skip re-prompting the LLM for any page that has not mutated structurally since the latest graph build.

## Constraints
- **C-1**: Python based execution without utilizing `npm` or local frontend bundler systems. 
- **C-12**: `vis.js` is bundled via public HTML CDN links cleanly inserted into the generated `.html` template natively.
- Edges must strictly abide by the ternary standard: `EXTRACTED` (regex wikilink explicitly established), `INFERRED` (LLM-detected connection w/ high confidence natively), `AMBIGUOUS` (low-confidence inference).

## Decision: Architecture Approach

We evaluated 2 distinct implementation approaches:

**Approach A (Monolithic Execution):**
Store the file parsing, LLM prompting, NetworkX algorithms, Louvain partitioning, and HTML templating inside one long 500-line `build_graph.py` CLI script executing procedurally.
*Pros*: Extremely fast to iterate. 
*Cons*: Untestable at a unit-level. Impossible to verify the behavior of the SHA caching logic or LLM json decoding arrays securely. 

**Approach B (Segmented Pipeline):**
Isolate boundaries deeply within `src/core`. 
- `src.core.graph_cache`: Extracts file contents, builds SHA buffers, detects `EXTRACTED` tokens using standard regex parameters.
- `src.core.graph_infer`: Routes cache misses into the LLM context limits prompting `INFERRED` edges structurally.
- `src.core.graph_build`: Executes `python-louvain` logic calculating topics and dumps the physical `graph.json` payload matrix mapping.
*Pros*: Satisfies `ENGINEERING.md` bounds perfectly exposing deterministic mapping arrays ready for unit test patching (e.g., verifying Louvain partition outputs accurately). 

**Decision**: Chosen **Approach B**. We will cleanly separate caching, inferencing, and clustering into `src/core/graph.py` endpoints wrapped cleanly natively by `tools/build_graph.py`.
