# Contract: S-10 Query Tool (CLI MVP)

| Field  | Value |
|--------|-------|
| Slice  | S-10 |
| Date   | 2026-04-12 |
| Status | DRAFT |
| Refs   | C-1, MVP Bounds, ENGINEERING.md |

---

## APIs

S-10 leverages standard internal components simulating RAG lookups mechanically executing purely through local LLM integrations. 

### `query_wiki(question: str, provider: str, config: Config, env: dict) -> str`

| Aspect | Spec |
|--------|------|
| Module | `src.core.query` |
| Input | `question`: Raw string evaluated directly from CLI user inputs. `Length: 1..2000 chars`. |
| Output | Returns definitively formatted Markdown string synthesizing locally gathered components targeting the exact question correctly. |
| Raises | Unrecoverable HTTP Drops natively bubble `SystemExit` cleanly mimicking S-3 routing bounds efficiently. |

---

## HTTP Boundary

Integrates fully against existing `src.core.llm.complete()` boundaries. 
- **Request Tiers**: Issues exactly `2` distinct `requests.post()` calls synchronously over strict sequentially blocking boundaries per query.
- **Payload Max Bounds**: Ensures Hop 1 payload `< 30,000` chars (`index.md` context bounding constraints). Ensures Hop 2 payload `< 30,000` chars natively (restricting file data accumulations dynamically to remain squarely underneath locally restrictive `4000` token limits mapping LM Studio setups securely).

---

## Data Structures

The system relies strictly on JSON schemas mapped strictly out of Hop 1 text decoding structures iteratively. 

### `Hop1 JSON Map`
| Field | Type | Description |
|-------|------|-------------|
| `target_path` | `str` | Physical relative path routing (`concepts/ai.md`). Array natively enforces `MAX_ROUTING = 3` targets cleanly avoiding variable explosions. |

---

## Boundary Limits

| Boundary | Limit | Rationale |
|----------|-------|-----------|
| Retrieval Ceiling | 3 Files | Enforces hard threshold blocking the LLM from requesting 20 files mimicking recursive RAG loops inherently violating memory context constraints drastically. |
| File Char Limit | 10,000 chars / file | Failsafe extraction constraint protecting strings during Hop 2 string concatenations dynamically. |
| Time to First Byte | ~2-5s | Due to the two-hop design mapping sequences natively, latency scales effectively linearly per prompt layer. |

---

## Tests

Execution Command: `pytest tests/unit/test_s10_query.py -v`

### Happy Path

| ID | Test | Input | Expected |
|----|------|-------|----------|
| T-10.01 | Valid RAG Synthesis | Standard question routing sequentially bounding index and targets properly. | `query_wiki()` executes correctly mapping 2 internal requests dynamically outputting raw markdown successfully extracting bounds. |

### Edge Cases

| ID | Test | Input | Expected |
|----|------|-------|----------|
| T-10.02 | Ghost File Request | LLM hallucinates `foo/bar.md` within Hop 1 array. | Extraction loop silently bypasses matching paths bypassing `FileNotFoundError` securely injecting remaining outputs cleanly. |
| T-10.03 | Blank Index Routing | Hop 1 output parses completely empty JSON `[]`. | Hop 2 synthesizes directly from the core LLM natively bypassing file injection cleanly yielding functional fallbacks. |
| T-10.04 | CLI `--save` Graceful Yield | Execution commands capturing specific `--save` modifiers directly onto the CLI execution. | CLI properly intercepts variable intercepting raw mapping strings returning unsupported logs and runs natively Read-Only securely. |

### Failure Cases

| ID | Test | Input | Expected |
|----|------|-------|----------|
| T-10.05 | Broken JSON Protocol | Hop 1 produces `Unstructured Text` failing to conform into standard format mappings dynamically. | Parsing functions handle JSONDecoderErrors correctly isolating issues skipping to Hop 2 fallbacks inherently gracefully preventing structural loops. |
| T-10.06 | Missing Index Exception | Physical `./vault/wiki/index.md` tracking mechanism vanishes natively blocking context parameters. | Hop 1 captures layout errors executing standard fallback or `SystemExit` cleanly blocking API token bleed natively. |

---

## Execution Method

### Automated Tests
Run integration paths verifying localized prompt generation structures against decoding mechanisms natively securely executing bounds manually:
```bash
pytest tests/unit/test_s10_query.py -v
```

### Manual Verification
Execute `tools/query.py "what..."` testing API integrations structurally bypassing visual components directly matching physical environments:
```bash
python tools/query.py "What is Attention mechanism?"
```
