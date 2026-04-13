# S-10 Query Tool (CLI MVP) — Pre-Implementation ADR

## Goal
Implement `tools/query.py "<question>"` establishing an intelligent read-only search mechanic across the local vault natively bypassing complex vector architectures.

## Systems Touched
- `tools/query.py`: Exposes CLI flag bindings accepting raw string queries (ignoring `--save` logic execution gracefully during MVP).
- `src/core/query.py`: Implements dual-hop LLM generation sequences interpreting `index.md` and recursively mapping context into final Markdown responses natively.

## Assumptions
- Token distributions. Gemini easily supports dumping 50 full articles into context natively relying upon flash attention (1M limit). Conversely, LM Studio heavily limits prompts to exactly 4,000 tokens locally bounds. The query mechanics absolutely must bound intelligently using discrete lookups over raw dumps to honor local environment ceilings. 

## Constraints
- **C-1**: Standard python execution (No external indexing databases, No `chromadb`, No embeddings arrays).
- **Anti-Goal 1**: "No RAG / vector search. The index file is the navigation mechanism."
- The `src.core` integrations must inherently execute queries securely leveraging `src.core.llm.complete()`.

## Decision: Architecture Approach

We evaluated 2 distinct approaches mapping dynamic file context natively without RAG engines:

**Approach A (Naïve Concatenation):**
Since vaults start small, mechanically concatenate `index.md` alongside the text of every single `.md` file explicitly into a massive string context window wrapping it with the user question. 
*Pros*: Single LLM API call cleanly isolating latency.
*Cons*: Immediately violates LM Studio 4k token limits upon crossing 5-8 total wiki pages. Absolutely breaks local privacy routing constraints forcing Google API fallbacks locally. 

**Approach B (2-Hop Semantic Routing):**
Because embeddings are forbidden, we utilize the LLM directly as the routing algorithm iteratively.
- **Hop 1 (Planner)**: Feed the LLM the question mapped against `index.md`. The LLM outputs a strictly structured JSON array recommending exact subset file paths it requires to answer the question (`["concepts/neural-networks.md"]`).
- **Data Load**: `src/core/query` parses the JSON, reads the top N requested paths from the physical disk sequentially accumulating their actual string contents natively.
- **Hop 2 (Synthesis)**: Feed the LLM the user question again, but directly inject the physical `.md` string contents requested from Hop 1. The LLM natively synthesizes and writes the definitive Markdown reply.
*Pros*: Honors tight 4k token limits natively. Aligns entirely with the Anti-Goal bounds utilizing `index.md` as the exclusive lookup map. 
*Cons*: Requires dual LLM sequential network timeouts sequentially costing slight latency blocks during CLI operations natively.

**Decision**: Chosen **Approach B**. Sequential routing is the only viable method resolving complex queries efficiently inside strict 4k token restrictions locally without vectorizing databases externally. 
