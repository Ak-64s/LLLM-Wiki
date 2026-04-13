# Contract: S-3 LLM Layer

| Field  | Value                                                         |
|--------|---------------------------------------------------------------|
| Slice  | S-3                                                           |
| Date   | 2026-04-12                                                    |
| Status | DRAFT                                                         |
| Refs   | AD-5, C-2, C-3, C-4, C-7, C-10, A-1, A-2, A-3              |

---

## APIs

S-3 exposes Python module APIs (no HTTP server). Two outbound HTTP boundaries exist:
the Gemini REST API and the LM Studio OpenAI-compatible API.

### `complete(provider: str, config: Config, env: dict, system_prompt: str, user_content: str) -> str`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.llm`                                                        |
| Input      | `provider` — `"gemini"` or `"lmstudio"`. `config` — `Config` instance from S-1. `env` — dict from `load_env()` (contains `GEMINI_API_KEY` when provider is gemini). `system_prompt` — instruction text for the LLM. `user_content` — the source text to process. |
| Output     | `str` — the LLM's response text, stripped of leading/trailing whitespace. |
| Raises     | `SystemExit` with message naming the provider and failure reason on any unrecoverable error. |
| Behavior   | 1. Determine chunk threshold for the provider via `get_threshold_chars()`. 2. If `len(user_content) > threshold_chars`: split using `chunk_text()`, call LLM once per chunk with the same `system_prompt`, concatenate responses with `"\n\n"`. 3. If `len(user_content) <= threshold_chars`: single LLM call. 4. Dispatch to `_call_gemini()` or `_call_lmstudio()` based on `provider`. |
| Guarantee  | **Never returns empty text.** If the LLM returns empty/whitespace-only response, raises `SystemExit` with message: `"LLM returned empty response ({provider})."` |
| Idempotent | No. LLM responses are non-deterministic.                             |
| Security   | API key passed via `env` dict. Never logged. Never included in error messages (C-7). |

### `_call_gemini(config: Config, env: dict, system_prompt: str, user_content: str) -> str`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.llm` (private)                                             |
| Input      | `config` — for `config.gemini_model`. `env` — must contain `"GEMINI_API_KEY"`. `system_prompt` + `user_content` — combined into the request payload. |
| Output     | `str` — the generated text from Gemini, stripped.                    |
| Raises     | `SystemExit` with message on: missing API key in env, HTTP error, invalid JSON response, empty response. |
| Boundary   | **Outbound HTTP** — see Gemini HTTP boundary spec below.             |

#### HTTP Boundary: Gemini REST API

| Aspect         | Spec                                                        |
|----------------|-------------------------------------------------------------|
| Method         | `POST`                                                      |
| URL            | `https://generativelanguage.googleapis.com/v1beta/models/{config.gemini_model}:generateContent?key={env["GEMINI_API_KEY"]}` |
| Request body   | `{"contents": [{"parts": [{"text": "{system_prompt}\n\n{user_content}"}]}]}` |
| Content-Type   | `application/json`                                          |
| Headers        | `Content-Type: application/json`                            |
| Expected 200   | JSON body: `{"candidates": [{"content": {"parts": [{"text": "..."}]}}]}`. Extract `candidates[0].content.parts[0].text`. |
| Expected 400   | Bad request (malformed payload). `SystemExit`: `"Gemini API error (400): bad request."` |
| Expected 403   | Invalid or missing API key. `SystemExit`: `"Gemini API error (403): invalid API key. Check GEMINI_API_KEY in .env."` |
| Expected 429   | Rate limit exceeded. `SystemExit`: `"Gemini API error (429): rate limit exceeded. Wait and retry."` |
| Expected 500   | Server error. `SystemExit`: `"Gemini API error (500): server error."` |
| Other !200     | `SystemExit`: `"Gemini API error ({status}): unexpected error."` |
| Connection err | `requests.ConnectionError` → `SystemExit`: `"Cannot connect to Gemini API."` |
| Timeout        | `requests.Timeout` → `SystemExit`: `"Gemini API request timed out."` |
| Timeout values | Connect: 30s. Read: 120s.                                   |
| Retry          | No automatic retry. Per L-8, no retry/backoff in MVP.       |
| Max request    | No enforced limit. Gemini accepts up to 1M tokens (~4M chars). Practical limit is the chunk threshold. |

### `_call_lmstudio(config: Config, system_prompt: str, user_content: str) -> str`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.llm` (private)                                             |
| Input      | `config` — for `config.lmstudio_endpoint`. `system_prompt` + `user_content` — structured as OpenAI chat messages. |
| Output     | `str` — the generated text from LM Studio, stripped.                 |
| Raises     | `SystemExit` with message on: connection error, timeout, non-200 status, invalid JSON response, empty response. |
| Boundary   | **Outbound HTTP** — see LM Studio HTTP boundary spec below.         |

#### HTTP Boundary: LM Studio Chat Completions

| Aspect         | Spec                                                        |
|----------------|-------------------------------------------------------------|
| Method         | `POST`                                                      |
| URL            | `{config.lmstudio_endpoint}/chat/completions`              |
| Request body   | `{"messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}], "temperature": 0.7, "max_tokens": -1}` |
| Content-Type   | `application/json`                                          |
| Headers        | `Content-Type: application/json`                            |
| Expected 200   | JSON body: `{"choices": [{"message": {"content": "..."}}]}`. Extract `choices[0].message.content`. |
| Expected !200  | Any non-200 status → `SystemExit`: `"LM Studio API error ({status})."` |
| Connection err | `requests.ConnectionError` → `SystemExit`: `"Cannot connect to LM Studio at {endpoint}. Is it running?"` |
| Timeout        | `requests.Timeout` → `SystemExit`: `"LM Studio request timed out."` |
| Timeout values | Connect: 30s. Read: 300s.                                   |
| Retry          | No automatic retry. User can retry via AD-9 flow if LM Studio is unreachable at startup. |
| `max_tokens`   | Set to `-1` (unlimited). LM Studio interprets this as "generate until stop token." |
| `temperature`  | `0.7`. Balances coherence and creativity for wiki synthesis. |

### `chunk_text(text: str, max_chars: int, overlap_chars: int) -> list[str]`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.chunking`                                                   |
| Input      | `text` — the full source text. `max_chars` — maximum characters per chunk. `overlap_chars` — number of characters to overlap between consecutive chunks. |
| Output     | `list[str]` — ordered list of text chunks. Always at least 1 element. Each chunk is `<= max_chars` in length. |
| Behavior   | 1. If `len(text) <= max_chars`: return `[text]` (no splitting). 2. Otherwise, split `text` into chunks of `max_chars` characters, with `overlap_chars` characters of overlap between consecutive chunks. Each chunk starts at `i * (max_chars - overlap_chars)`. 3. Last chunk may be shorter than `max_chars`. |
| Validation | `max_chars` must be > 0. `overlap_chars` must be >= 0 and < `max_chars`. Violations raise `ValueError`. |
| Idempotent | Yes. Pure function.                                                   |

### `get_threshold_chars(provider: str, config: Config) -> int`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.chunking`                                                   |
| Input      | `provider` — `"gemini"` or `"lmstudio"`. `config` — `Config` instance. |
| Output     | `int` — the character-based chunk threshold for the given provider.  |
| Behavior   | Returns `config.chunk_threshold_lmstudio * 4` for lmstudio, `config.chunk_threshold_gemini * 4` for gemini. The `* 4` converts token thresholds to approximate character thresholds (English avg ~4 chars/token). |
| Idempotent | Yes. Pure function.                                                   |

### `get_overlap_chars(config: Config) -> int`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.chunking`                                                   |
| Input      | `config` — `Config` instance.                                        |
| Output     | `int` — the character-based overlap for chunking.                    |
| Behavior   | Returns `config.chunk_overlap * 4`. Same token-to-char conversion.   |
| Idempotent | Yes. Pure function.                                                   |

---

## Data Structures

### Config fields consumed by S-3

S-3 reads these fields from the `Config` dataclass (defined in S-1):

| Field                        | Type  | Used by        | Purpose                                       |
|------------------------------|-------|----------------|------------------------------------------------|
| `gemini_model`               | `str` | `_call_gemini` | Model name in Gemini REST API URL.             |
| `lmstudio_endpoint`         | `str` | `_call_lmstudio`| Base URL for LM Studio API.                    |
| `chunk_threshold_lmstudio`   | `int` | `get_threshold_chars` | Token threshold for LM Studio chunking.  |
| `chunk_threshold_gemini`     | `int` | `get_threshold_chars` | Token threshold for Gemini chunking.     |
| `chunk_overlap`              | `int` | `get_overlap_chars` | Token overlap between chunks.              |

### Environment dict consumed by S-3

| Key              | Type  | Required by      | Constraints                              |
|------------------|-------|------------------|------------------------------------------|
| `GEMINI_API_KEY` | `str` | `_call_gemini`   | Non-empty. Not logged. Not printed (C-7). Present when `provider == "gemini"`. |

### Internal Constants

| Constant                 | Type  | Value   | Rationale                                         |
|--------------------------|-------|---------|----------------------------------------------------|
| `_GEMINI_CONNECT_TIMEOUT`| `int` | `30`    | Cloud API. DNS + TLS handshake may be slow.        |
| `_GEMINI_READ_TIMEOUT`   | `int` | `120`   | LLM generation for large inputs can take 1-2 min.  |
| `_LMSTUDIO_CONNECT_TIMEOUT`| `int`| `30`   | Local endpoint. Generous for cold start.           |
| `_LMSTUDIO_READ_TIMEOUT` | `int` | `300`   | Local models are slower. 5 min upper bound.        |
| `_GEMINI_API_BASE`       | `str` | `"https://generativelanguage.googleapis.com/v1beta"` | Gemini REST API base URL. |
| `_CHARS_PER_TOKEN`       | `int` | `4`     | English average. Used for token-to-char conversion. |
| `_TEMPERATURE`           | `float`| `0.7`  | Balances coherence and creativity.                 |

---

## Boundary Limits

| Boundary                         | Limit               | Rationale                                          |
|----------------------------------|----------------------|----------------------------------------------------|
| Gemini connect timeout           | 30 seconds           | Cloud API. TLS + DNS may be slow on first call.    |
| Gemini read timeout              | 120 seconds          | LLM generation for large prompts is slow.          |
| LM Studio connect timeout        | 30 seconds           | Local endpoint. Generous for cold start.           |
| LM Studio read timeout           | 300 seconds          | Local models with 9B params are slow.              |
| Chunk `max_chars`                | Must be > 0          | Zero or negative would produce infinite loop.      |
| Chunk `overlap_chars`            | Must be >= 0 and < `max_chars` | Overlap >= max_chars means chunks never advance. |
| Chars-per-token ratio            | 4                    | English average. Heuristic, not exact.             |
| LM Studio default `max_tokens`   | -1 (unlimited)       | Let model generate until stop token.               |
| LM Studio `temperature`          | 0.7                  | Fixed for MVP. Not user-configurable.              |
| LLM response text                | Must be non-empty    | Empty response → `SystemExit`.                     |

No rate limits are enforced by S-3. Gemini free tier has its own rate limits (L-8).
No retry/backoff in MVP.

---

## Tests

Execution method: `pytest tests/unit/test_s3_llm.py -v`

Dependencies: `pytest`, `requests`. All HTTP calls are mocked. Tests must be
deterministic and run offline. No real LLM calls.

### Chunking

#### Happy Path

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-3.01 | Text under threshold returns single chunk  | `text="Hello"`, `max_chars=100`, `overlap=10` | Returns `["Hello"]`.                           |
| T-3.02 | Text over threshold splits into chunks     | `text="A"*200`, `max_chars=100`, `overlap=20` | Returns list with 3 chunks. Each <= 100 chars. |
| T-3.03 | Overlap present between consecutive chunks | `text="ABCDEFGHIJ"*10`, `max_chars=50`, `overlap=10` | Chunk N ends with same chars that chunk N+1 starts with. Overlap region is 10 chars. |
| T-3.04 | Last chunk may be shorter than max_chars   | `text="A"*150`, `max_chars=100`, `overlap=0` | Returns `["A"*100, "A"*50]`. Second chunk is 50 chars. |
| T-3.05 | get_threshold_chars for gemini             | `config.chunk_threshold_gemini=750000`   | Returns `3000000` (750000 * 4).                 |
| T-3.06 | get_threshold_chars for lmstudio           | `config.chunk_threshold_lmstudio=4000`   | Returns `16000` (4000 * 4).                     |
| T-3.07 | get_overlap_chars                          | `config.chunk_overlap=200`               | Returns `800` (200 * 4).                        |

#### Edge Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-3.08 | Text exactly at threshold (no split)       | `text="A"*100`, `max_chars=100`, `overlap=10` | Returns `["A"*100]`. Single chunk.             |
| T-3.09 | Overlap of zero                            | `text="A"*200`, `max_chars=100`, `overlap=0` | Returns `["A"*100, "A"*100]`. No overlap.      |
| T-3.10 | Single character text                      | `text="X"`, `max_chars=100`, `overlap=10` | Returns `["X"]`.                                |
| T-3.11 | Overlap almost equals max_chars            | `text="A"*200`, `max_chars=100`, `overlap=99` | Chunks advance by 1 char each. Many chunks.    |

#### Failure Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-3.12 | max_chars is zero                          | `max_chars=0`                            | `ValueError`.                                    |
| T-3.13 | max_chars is negative                      | `max_chars=-1`                           | `ValueError`.                                    |
| T-3.14 | overlap equals max_chars                   | `max_chars=100`, `overlap=100`           | `ValueError`.                                    |
| T-3.15 | overlap exceeds max_chars                  | `max_chars=100`, `overlap=200`           | `ValueError`.                                    |
| T-3.16 | negative overlap                           | `overlap=-1`                             | `ValueError`.                                    |

### Gemini Completion

#### Happy Path

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-3.17 | Gemini returns valid response              | Mock POST 200, JSON: `{"candidates":[{"content":{"parts":[{"text":"Response text"}]}}]}` | Returns `"Response text"`.                     |
| T-3.18 | Gemini response with leading/trailing whitespace | Mock POST 200, text: `"  padded  "` | Returns `"padded"` (stripped).                  |
| T-3.19 | complete() with gemini provider            | Mock _call_gemini returning text         | Returns the text. No chunking needed for short input. |

#### Edge Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-3.20 | Empty system prompt                        | `system_prompt=""`, valid `user_content` | Proceeds normally. Empty system prompt is valid. |
| T-3.21 | Multi-chunk Gemini completion              | `user_content` longer than threshold chars, mock _call_gemini returning `"Part N"` per call | Returns concatenated `"Part 1\n\nPart 2"`.      |

#### Failure Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-3.22 | Gemini 403 invalid key                     | Mock POST 403                            | `SystemExit`. Message contains `"403"` and `"API key"`. |
| T-3.23 | Gemini 429 rate limit                      | Mock POST 429                            | `SystemExit`. Message contains `"429"` and `"rate limit"`. |
| T-3.24 | Gemini 500 server error                    | Mock POST 500                            | `SystemExit`. Message contains `"500"`.          |
| T-3.25 | Gemini connection error                    | Mock `requests.ConnectionError`          | `SystemExit`. Message contains `"Cannot connect"` and `"Gemini"`. |
| T-3.26 | Gemini timeout                             | Mock `requests.Timeout`                  | `SystemExit`. Message contains `"timed out"` and `"Gemini"`. |
| T-3.27 | Gemini returns empty response text         | Mock POST 200, text: `""`               | `SystemExit`. Message contains `"empty response"`. |
| T-3.28 | Gemini returns malformed JSON              | Mock POST 200, body is not valid JSON    | `SystemExit`. Message contains `"Gemini"`.       |
| T-3.29 | Gemini JSON missing candidates field       | Mock POST 200, JSON: `{}`               | `SystemExit`. Message contains `"Gemini"`.       |

### LM Studio Completion

#### Happy Path

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-3.30 | LM Studio returns valid response           | Mock POST 200, JSON: `{"choices":[{"message":{"content":"LM response"}}]}` | Returns `"LM response"`.                       |
| T-3.31 | LM Studio response with whitespace         | Mock POST 200, content: `"  padded  "`  | Returns `"padded"` (stripped).                   |
| T-3.32 | complete() with lmstudio provider          | Mock _call_lmstudio returning text       | Returns the text. No chunking needed for short input. |

#### Edge Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-3.33 | Multi-chunk LM Studio completion           | `user_content` longer than threshold chars, mock _call_lmstudio returning `"Part N"` per call | Returns concatenated parts.                     |

#### Failure Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-3.34 | LM Studio connection refused               | Mock `requests.ConnectionError`          | `SystemExit`. Message contains `"Cannot connect"` and `"LM Studio"`. |
| T-3.35 | LM Studio timeout                          | Mock `requests.Timeout`                  | `SystemExit`. Message contains `"timed out"` and `"LM Studio"`. |
| T-3.36 | LM Studio returns 500                      | Mock POST 500                            | `SystemExit`. Message contains `"500"`.          |
| T-3.37 | LM Studio returns empty response text      | Mock POST 200, content: `""`            | `SystemExit`. Message contains `"empty response"`. |
| T-3.38 | LM Studio returns malformed JSON           | Mock POST 200, body is not valid JSON    | `SystemExit`. Message contains `"LM Studio"`.    |
| T-3.39 | LM Studio JSON missing choices field       | Mock POST 200, JSON: `{}`               | `SystemExit`. Message contains `"LM Studio"`.    |

### Dispatch & Validation

#### Happy Path

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-3.40 | complete() dispatches to gemini            | `provider="gemini"`, mock _call_gemini   | _call_gemini is called. Returns its response.   |
| T-3.41 | complete() dispatches to lmstudio          | `provider="lmstudio"`, mock _call_lmstudio | _call_lmstudio is called. Returns its response.|

#### Failure Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-3.42 | Invalid provider name                      | `provider="openai"`                      | `SystemExit`. Message contains `"openai"` and `"invalid provider"`. |
| T-3.43 | complete() with empty user_content         | `user_content=""`                        | `SystemExit`. Message contains `"empty"`.        |

---

## Execution Method

### Unit Tests

```bash
pip install -r requirements.txt
pip install pytest
pytest tests/unit/test_s3_llm.py -v
```

All tests mock HTTP calls via `unittest.mock.patch`:
- Gemini: `requests.post` is mocked. No real API calls.
- LM Studio: `requests.post` is mocked. No real local server needed.
- Chunking: pure function tests. No mocking needed.

Tests must be deterministic and run offline.

### Manual Smoke Test

```bash
# 1. Chunking works correctly
python -c "
from src.core.chunking import chunk_text
chunks = chunk_text('A' * 200, max_chars=100, overlap_chars=20)
print(f'Chunks: {len(chunks)}, sizes: {[len(c) for c in chunks]}')
"

# 2. Gemini completion (requires GEMINI_API_KEY in .env and internet)
python -c "
from src.core.config import load_config, load_env
from src.core.llm import complete
config = load_config()
env = load_env('gemini')
response = complete('gemini', config, env, 'You are a helpful assistant.', 'Say hello.')
print(response[:200])
"

# 3. LM Studio completion (requires LM Studio running)
python -c "
from src.core.config import load_config, load_env
from src.core.llm import complete
config = load_config()
env = load_env('lmstudio')
response = complete('lmstudio', config, env, 'You are a helpful assistant.', 'Say hello.')
print(response[:200])
"

# 4. Invalid provider fails fast
python -c "
from src.core.config import load_config, load_env
from src.core.llm import complete
complete('openai', load_config(), {}, 'sys', 'usr')
"
# Expected: SystemExit with "invalid provider"
```

---

## ENGINEERING.md Validation Checklist

| Principle              | Satisfied?                                                        |
|------------------------|-------------------------------------------------------------------|
| Explicit > implicit    | Provider dispatch is explicit. Chunking thresholds derived from config with named constant (`_CHARS_PER_TOKEN`). API URLs fully specified. |
| Simple > clever        | Single `complete()` function. Two private HTTP helpers. Separate chunking module. No class hierarchy. |
| Contracts define behavior | This document. Every API has input/output/raises spec. Both HTTP boundaries fully specified. |
| Systems fail at boundaries | Both HTTP boundaries specify timeout, status codes, connection errors, and response validation. |
| Observable / debuggable | Error messages name the provider and specific failure. HTTP status codes included in error messages. |
| Validate all inputs    | Provider name validated (closed enum). `user_content` validated (non-empty). Chunk parameters validated (positive, non-overlapping). |
| Fail fast and clearly  | `SystemExit` on every failure path. Empty LLM response caught. Malformed JSON caught. |
| Never swallow errors   | `requests` exceptions caught and re-raised with provider context. JSON parse errors caught with provider name. |
| No hardcoded secrets   | API key from `env` dict (loaded by S-1's `load_env()`). Never logged, never in error messages (C-7). Key passed as URL query parameter to Gemini API per their documentation. |
| Treat inputs as untrusted | LLM response validated (non-empty, valid JSON structure). Chunk sizes validated. |
