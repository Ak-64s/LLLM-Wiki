# ADR: LLM Completion Architecture

| Field   | Value                                                    |
|---------|----------------------------------------------------------|
| Slice   | S-3                                                      |
| Date    | 2026-04-12                                               |
| Status  | ACCEPTED                                                 |
| Decides | How the tool calls LLM providers and handles chunking    |

---

## Context

S-3 is the first slice to make outbound LLM calls. Every downstream slice (S-4
through S-7) uses `complete()` to transform extracted text into wiki content.
The architectural choice here determines the HTTP calling pattern, error
handling, chunking strategy, and the extensibility model for providers.

**Binding constraints:**
- C-2: Providers are Gemini and LM Studio only. No others in MVP.
- C-3: LM Studio endpoint configurable in config.json.
- C-4: Gemini model `gemini-3-flash-preview`, 1M token context.
- C-7: API keys in `.env` only. Never in source, config, or error messages.
- C-10: Chunk thresholds configurable (LM Studio 4,000 tokens, Gemini 750,000 tokens).
- AD-5: Chunking is provider-specific with explicit thresholds and overlap.

**Integration surface:** S-3 consumes S-1's `Config` and `load_env()`. It is
consumed by S-4+ (ingest, page generation, query).

---

## Approach 1 — Flat functions with `requests` [CHOSEN]

A single public function `complete(provider, config, env, system_prompt,
user_content)` dispatches to two private helpers `_call_gemini()` and
`_call_lmstudio()`. Chunking lives in a separate module (`src/core/chunking.py`)
with pure functions. All HTTP calls use `requests.post()` directly.

```python
def complete(provider, config, env, system_prompt, user_content) -> str:
    threshold = get_threshold_chars(provider, config)
    if len(user_content) > threshold:
        chunks = chunk_text(user_content, threshold, overlap)
        return "\n\n".join(_call(provider, ..., chunk) for chunk in chunks)
    return _call(provider, ..., user_content)
```

**Strengths:**
- Zero new dependencies. `requests` is already in use from S-1/S-2.
- Consistent with S-1/S-2 pattern: flat functions, `_fail()` for errors.
- Both HTTP boundaries fully specified with timeouts, status codes, and
  error messages that name the provider.
- Chunking is a pure, independently testable module.

**Weaknesses:**
- Adding a 3rd provider requires another `elif` and private function.
- No SDK-level features (automatic retries, streaming, token counting).

## Approach 2 — Provider SDKs (`google-genai`, `openai`) [REJECTED]

Use `google-genai` for Gemini and the `openai` Python SDK for LM Studio's
OpenAI-compatible API.

**Why rejected:**
- Two new heavyweight dependencies for two HTTP endpoints.
- SDK abstractions hide timeout, retry, and error behavior — violating
  "Explicit > implicit" and "Systems fail at boundaries."
- LM Studio's OpenAI compatibility is partial; SDK assumptions about
  model listing, token counting, and streaming may not hold.
- S-1/S-2 established raw `requests` as the HTTP pattern. Mixing SDKs
  with raw requests increases cognitive load.
- Violates ENGINEERING.md: "Simple > clever", "Never trust other modules
  blindly."

---

## Why Approach 1 wins

1. **No new dependencies.** `requests` is already installed. Zero supply-chain
   risk increase.
2. **Both boundaries are explicit.** Every timeout, status code, and error
   message is defined in the contract. No hidden retry or backoff.
3. **Chunking is isolated.** Pure functions with validation. Independently
   testable. No coupling to HTTP layer.
4. **Consistent with S-1/S-2.** Same module structure, same error pattern,
   same `_fail()` convention.
5. **Adding a 3rd provider is a small diff.** One `elif` in `complete()`, one
   private function. Not worth pre-building a plugin system.

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Token-to-char heuristic (4 chars/token) | Avoids tokenizer dependency. English average is ~4. Acceptable for chunking threshold decisions. |
| No retry/backoff | Per L-8. Free-tier Gemini rate limits are outside our control. User can re-run. |
| Empty response is fatal | LLM returning empty text means synthesis failed. Downstream slices cannot recover. Fail fast. |
| `temperature = 0.7` fixed | Not user-configurable in MVP. Balances coherence and creativity for wiki synthesis. |
| Chunk overlap from config | Prevents context loss at seam boundaries. Config-driven so users can tune per use case. |
| API key in URL query param (Gemini) | Per Gemini REST API documentation. Not logged or included in error messages. |

---

## Consequences

1. `complete()` is the single entry point for all LLM calls in the system.
   S-4+ never calls `_call_gemini()` or `_call_lmstudio()` directly.
2. Chunking is transparent to callers. `complete()` handles splitting and
   concatenation internally.
3. Error messages always name the provider (Gemini or LM Studio) and the
   failure type (HTTP status, timeout, connection, empty response, bad JSON).
4. No streaming. Responses are buffered and returned as a complete string.
5. No token counting. Character-based heuristic is sufficient for chunking
   threshold decisions.

---

## ENGINEERING.md Checklist

| Principle              | Application                                                    |
|------------------------|----------------------------------------------------------------|
| Explicit > implicit    | Provider dispatch is explicit. Timeouts, status codes, and error messages all specified. Token-to-char ratio is a named constant. |
| Simple > clever        | Two private HTTP functions. One public dispatch. Separate chunking module. No class hierarchy. |
| Contracts define behavior | Contract doc defines every API, both HTTP boundaries, all failure modes. |
| Fail fast and clearly  | `SystemExit` on every failure path. Empty LLM response caught. Invalid provider caught. |
| Validate all inputs    | Provider name validated. `user_content` validated (non-empty). Chunk parameters validated (positive, non-overlapping). |
| Never swallow errors   | `requests` exceptions caught and re-raised with provider context. JSON parse errors caught with provider name. |
| Systems fail at boundaries | Both HTTP boundaries specify timeouts, status codes, connection errors, and response validation. |
| No hardcoded secrets   | API key from `env` dict. Never logged. Never in error messages (C-7). |
