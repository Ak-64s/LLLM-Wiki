# Contract: S-1 Foundation

| Field  | Value                                                         |
|--------|---------------------------------------------------------------|
| Slice  | S-1                                                           |
| Date   | 2026-04-12                                                    |
| Status | DRAFT                                                         |
| Refs   | AD-5, AD-9, C-3, C-4, C-7, C-8, C-10, I-9                   |

---

## APIs

S-1 exposes Python module APIs (no HTTP server). One HTTP boundary exists: the LM Studio
health check (outbound GET).

### `load_config(path: str = "config.json") -> Config`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.config`                                                     |
| Input      | `path` — filesystem path to JSON config file. Max length: 260 chars (Windows `MAX_PATH`). |
| Output     | `Config` dataclass instance with all fields populated.                |
| Raises     | `SystemExit(1)` with message naming the missing file if file not found. |
|            | `SystemExit(1)` with message naming the invalid field if JSON is malformed. |
|            | `SystemExit(1)` with message naming the missing field if a required field is absent. |
|            | `SystemExit(1)` with message naming the field and expected type if a field has the wrong type. |
| Idempotent | Yes. Pure read. No side effects.                                      |

### `load_env() -> dict[str, str]`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.config`                                                     |
| Input      | None (reads `.env` file and/or environment variables).                |
| Output     | `dict` with key `"GEMINI_API_KEY"` -> str value.                     |
| Raises     | `SystemExit(1)` with message: `"Missing environment variable: GEMINI_API_KEY. Set it in .env or your shell environment."` |
| Idempotent | Yes. Reads only.                                                      |
| Security   | Never logs or prints the API key value. Only checks presence (C-7).  |

### `select_provider(config: Config) -> str`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.provider`                                                   |
| Input      | `Config` instance. Reads `config.default_provider`.                   |
| Output     | `str` — one of `"gemini"` or `"lmstudio"`. No other values.         |
| Behavior   | If `default_provider` is `"gemini"` or `"lmstudio"`, return it directly. If `"ask"`, prompt user interactively: `"Select provider:\n  [1] Gemini\n  [2] LM Studio\nChoice: "`. |
| Validation | If `default_provider` is not one of `"gemini"`, `"lmstudio"`, `"ask"`: `SystemExit(1)` with message naming the invalid value and listing valid options. |
| Idempotent | No. May prompt for user input.                                        |

### `check_lmstudio(endpoint: str) -> bool`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.provider`                                                   |
| Input      | `endpoint` — base URL string (e.g. `"http://localhost:1234/v1"`). Max length: 2048 chars. |
| Output     | `True` if GET `{endpoint}/models` returns HTTP 200. `False` otherwise. |
| Timeout    | 5 seconds connect timeout, 5 seconds read timeout.                    |
| Boundary   | **Outbound HTTP** — see HTTP boundary spec below.                    |
| Idempotent | Yes. Read-only GET.                                                   |

#### HTTP Boundary: LM Studio Health Check

| Aspect         | Spec                                                        |
|----------------|-------------------------------------------------------------|
| Method         | `GET`                                                       |
| URL            | `{config.lmstudio_endpoint}/models`                        |
| Request body   | None                                                        |
| Headers        | None required                                               |
| Expected 200   | JSON body with `"data"` key (OpenAI-compatible model list). Body content is not parsed — only status code matters. |
| Expected !200  | Any non-200 status, connection refused, DNS failure, or timeout → treat as unreachable. |
| Timeout        | Connect: 5s. Read: 5s. Total max: 10s.                     |
| Retry          | Not retried automatically. Caller (`ensure_provider_ready`) handles the retry loop. |

### `ensure_provider_ready(provider: str, config: Config) -> str`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.provider`                                                   |
| Input      | `provider` — `"gemini"` or `"lmstudio"`. `Config` instance.         |
| Output     | `str` — final provider name (`"gemini"` or `"lmstudio"`).           |
| Behavior   | If `provider == "gemini"`: return `"gemini"` immediately (no check needed). If `provider == "lmstudio"`: call `check_lmstudio()`. On success, return `"lmstudio"`. On failure, enter AD-9 retry loop. |
| AD-9 loop  | Print: `"LM Studio is not reachable at {endpoint}. Start it and press Enter to retry, or type 'switch' to use Gemini instead."` Wait for input. Empty input (Enter) → retry `check_lmstudio()`. Input `"switch"` (case-insensitive) → return `"gemini"`. Any other input → repeat prompt. Loop has no max iteration limit. |
| Idempotent | No. Interactive I/O.                                                  |

### `ensure_directories(config: Config) -> None`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.dirs`                                                       |
| Input      | `Config` instance. Reads `vault_path` and `sources_path`.            |
| Output     | None. Side effect: directories created on filesystem.                |
| Creates    | `{vault_path}/wiki/sources/`, `{vault_path}/wiki/entities/`, `{vault_path}/wiki/concepts/`, `{vault_path}/graph/`, `{sources_path}/articles/`, `{sources_path}/pdfs/`, `{sources_path}/notes/` |
| Validation | C-8 check: resolve both paths to absolute. If `sources_path` starts with or equals `vault_path`, raise `SystemExit(1)` with message: `"Sources path '{sources_path}' must not be inside vault path '{vault_path}' (C-8)."` |
| Behavior   | Uses `os.makedirs(path, exist_ok=True)` for each directory. Already-existing dirs are a no-op. Logs each newly created directory to stdout. |
| Raises     | `SystemExit(1)` on C-8 violation. `OSError` propagated on permission failure (not swallowed). |
| Idempotent | Yes. Safe to call multiple times.                                     |

---

## Data Structures

### `Config` Dataclass

| Field                              | Type    | Required | Default                          | Constraints                        |
|------------------------------------|---------|----------|----------------------------------|------------------------------------|
| `vault_path`                       | `str`   | YES      | —                                | Non-empty. Max 260 chars. Must be a valid filesystem path. |
| `sources_path`                     | `str`   | YES      | —                                | Non-empty. Max 260 chars. Must not be inside `vault_path` (C-8). |
| `default_provider`                 | `str`   | NO       | `"gemini"`                       | One of: `"gemini"`, `"lmstudio"`, `"ask"`. |
| `lmstudio_endpoint`               | `str`   | NO       | `"http://localhost:1234/v1"`     | Must start with `http://` or `https://`. Max 2048 chars. |
| `gemini_model`                     | `str`   | NO       | `"gemini-3-flash-preview"`       | Non-empty. Max 128 chars.          |
| `chunk_threshold_lmstudio`         | `int`   | NO       | `4000`                           | Positive integer. Min: 100. Max: 1,000,000. |
| `chunk_threshold_gemini`           | `int`   | NO       | `750000`                         | Positive integer. Min: 100. Max: 10,000,000. |
| `chunk_overlap`                    | `int`   | NO       | `200`                            | Non-negative integer. Must be < min(chunk_threshold_lmstudio, chunk_threshold_gemini). |
| `graph_infer_confidence_threshold` | `float` | NO       | `0.5`                            | Range: 0.0 to 1.0 inclusive.       |

Nullability: No field is nullable. All fields have a concrete value after `load_config()` returns.

### `config.json` Schema

Flat JSON object. No nesting. All keys are snake_case strings matching `Config` field names exactly.

```json
{
  "vault_path":                       "string (required)",
  "sources_path":                     "string (required)",
  "default_provider":                 "string (optional)",
  "lmstudio_endpoint":               "string (optional)",
  "gemini_model":                     "string (optional)",
  "chunk_threshold_lmstudio":         "integer (optional)",
  "chunk_threshold_gemini":           "integer (optional)",
  "chunk_overlap":                    "integer (optional)",
  "graph_infer_confidence_threshold": "number (optional)"
}
```

Max file size: 4 KB. Any JSON file exceeding this is rejected (likely corrupted or wrong file).

### Environment Variables

| Variable         | Type   | Required           | Constraints                              |
|------------------|--------|--------------------|------------------------------------------|
| `GEMINI_API_KEY` | `str`  | YES (for Gemini)   | Non-empty. Not logged. Not printed. Loaded from `.env` or shell environment. |

---

## Boundary Limits

| Boundary                 | Limit                       | Rationale                              |
|--------------------------|-----------------------------|----------------------------------------|
| config.json file size    | 4 KB max                    | Config is ~10 fields. Anything larger is wrong. |
| config.json path length  | 260 chars max               | Windows MAX_PATH.                      |
| LM Studio health check   | 5s connect + 5s read        | Fail fast. User retries via AD-9 loop. |
| Directory creation       | 10 directories max per call | Fixed set. Not user-configurable.      |
| Provider name values     | 3 values: `gemini`, `lmstudio`, `ask` | Closed enum. Reject anything else. |
| Chunk threshold range    | 100 to 10,000,000 tokens    | Below 100 is unusable. Above 10M exceeds any current model. |
| Confidence threshold     | 0.0 to 1.0                  | Probability range.                     |
| Endpoint URL length      | 2048 chars max              | Standard URL limit.                    |

No rate limits apply to S-1. No latency targets for MVP (PROJECT_BRIEF.md). LM Studio health
check latency is bounded by the 10s total timeout.

---

## Tests

Execution method: `pytest tests/unit/test_s1_foundation.py -v`

Dependencies: `pytest`, `python-dotenv`, `requests`. No external services required for unit
tests (LM Studio health check is mocked).

### Config Loading

#### Happy Path

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-1.01 | Load valid config with all fields           | JSON with all 9 fields, valid values    | `Config` instance with all fields matching JSON |
| T-1.02 | Load config with only required fields       | JSON with `vault_path` + `sources_path` | `Config` with defaults for all optional fields  |
| T-1.03 | Load env with GEMINI_API_KEY set            | Env var `GEMINI_API_KEY=test-key`       | Returns `{"GEMINI_API_KEY": "test-key"}`        |

#### Edge Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-1.04 | Config with extra unknown fields            | JSON with valid fields + `"foo": "bar"` | `Config` loaded successfully. Unknown fields ignored. |
| T-1.05 | Chunk overlap equals zero                   | `chunk_overlap: 0`                      | Valid. `Config` created with `chunk_overlap=0`. |
| T-1.06 | Confidence threshold at boundaries          | `0.0` and `1.0`                         | Both valid. `Config` created.                   |
| T-1.07 | Paths with spaces                           | `"vault_path": "my vault"`              | Valid. `Config` created. Path preserved as-is.  |
| T-1.08 | GEMINI_API_KEY in shell env, no .env file   | Shell env set, no .env file             | Returns key from shell env.                     |

#### Failure Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-1.09 | Config file not found                       | Non-existent path                       | `SystemExit(1)`. Message names the file path.   |
| T-1.10 | Config file is invalid JSON                 | `{broken json`                          | `SystemExit(1)`. Message says "invalid JSON".   |
| T-1.11 | Missing required field: vault_path          | JSON without `vault_path`               | `SystemExit(1)`. Message: `"Missing required config field: vault_path"`. |
| T-1.12 | Missing required field: sources_path        | JSON without `sources_path`             | `SystemExit(1)`. Message: `"Missing required config field: sources_path"`. |
| T-1.13 | Wrong type: vault_path is integer           | `"vault_path": 123`                     | `SystemExit(1)`. Message names field and expected type `str`. |
| T-1.14 | Wrong type: chunk_threshold_lmstudio is str | `"chunk_threshold_lmstudio": "4000"`    | `SystemExit(1)`. Message names field and expected type `int`. |
| T-1.15 | Chunk threshold below minimum               | `"chunk_threshold_lmstudio": 50`        | `SystemExit(1)`. Message: threshold must be >= 100. |
| T-1.16 | Chunk threshold above maximum               | `"chunk_threshold_gemini": 99999999`    | `SystemExit(1)`. Message: threshold must be <= 10,000,000. |
| T-1.17 | Confidence threshold out of range           | `"graph_infer_confidence_threshold": 1.5`| `SystemExit(1)`. Message: must be 0.0–1.0.    |
| T-1.18 | Chunk overlap >= chunk threshold            | `overlap: 5000`, `lmstudio: 4000`       | `SystemExit(1)`. Message: overlap must be < smallest threshold. |
| T-1.19 | Empty vault_path                            | `"vault_path": ""`                      | `SystemExit(1)`. Message: vault_path must be non-empty. |
| T-1.20 | Invalid default_provider                    | `"default_provider": "openai"`          | `SystemExit(1)`. Message names invalid value, lists valid options. |
| T-1.21 | Endpoint missing http(s) prefix             | `"lmstudio_endpoint": "localhost:1234"` | `SystemExit(1)`. Message: must start with http:// or https://. |
| T-1.22 | Config file exceeds 4 KB                    | 5 KB file                               | `SystemExit(1)`. Message: config file too large. |
| T-1.23 | Missing GEMINI_API_KEY                      | No env var, no .env file                | `SystemExit(1)`. Message: `"Missing environment variable: GEMINI_API_KEY"`. |

### Provider Selection

#### Happy Path

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-1.24 | Select gemini from config                   | `default_provider: "gemini"`            | Returns `"gemini"`.                             |
| T-1.25 | Select lmstudio from config                 | `default_provider: "lmstudio"`          | Returns `"lmstudio"`.                           |
| T-1.26 | LM Studio reachable                         | Mock GET 200 on `/models`               | `check_lmstudio()` returns `True`.              |
| T-1.27 | Ensure gemini ready (no check needed)       | `provider="gemini"`                     | Returns `"gemini"` immediately.                 |
| T-1.28 | Ensure lmstudio ready (reachable)           | Mock GET 200                            | Returns `"lmstudio"`.                           |

#### Edge Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-1.29 | Interactive selection: user types "1"       | `default_provider: "ask"`, stdin `"1"`  | Returns `"gemini"`.                             |
| T-1.30 | Interactive selection: user types "2"       | `default_provider: "ask"`, stdin `"2"`  | Returns `"lmstudio"`.                           |
| T-1.31 | Interactive selection: invalid then valid   | stdin `"3"` then `"1"`                  | Reprompts, then returns `"gemini"`.             |

#### Failure Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-1.32 | LM Studio unreachable (connection refused)  | Mock connection error                   | `check_lmstudio()` returns `False`.             |
| T-1.33 | LM Studio timeout                           | Mock timeout after 5s                   | `check_lmstudio()` returns `False`.             |
| T-1.34 | LM Studio returns 500                       | Mock GET 500                            | `check_lmstudio()` returns `False`.             |
| T-1.35 | AD-9 retry then success                     | First call: mock fail. stdin: Enter. Second call: mock 200. | Returns `"lmstudio"`. |
| T-1.36 | AD-9 switch to Gemini                       | Mock fail. stdin: `"switch"`            | Returns `"gemini"`.                             |
| T-1.37 | AD-9 switch case-insensitive                | Mock fail. stdin: `"SWITCH"`            | Returns `"gemini"`.                             |

### Directory Initialization

#### Happy Path

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-1.38 | Create all directories from scratch         | Empty temp dir, valid config            | All 10 directories exist after call.            |
| T-1.39 | Idempotent: call twice                      | Call `ensure_directories()` twice       | No error. Same directories exist.               |

#### Edge Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-1.40 | Some directories already exist              | Pre-create `vault/wiki/`, call function | Missing dirs created. Existing dirs untouched.  |
| T-1.41 | Paths with spaces                           | `vault_path: "my vault"`               | Directories created at path with spaces.        |

#### Failure Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-1.42 | C-8 violation: sources inside vault         | `vault_path: "vault"`, `sources_path: "vault/sources"` | `SystemExit(1)`. Message names both paths and cites C-8. |
| T-1.43 | C-8 violation: sources equals vault         | Both paths identical                    | `SystemExit(1)`.                                |
| T-1.44 | Read-only directory (permission error)      | Temp dir with no write permission       | `OSError` propagated. Not swallowed.            |

---

## Execution Method

### Unit Tests

```bash
pip install -r requirements.txt
pip install pytest
pytest tests/unit/test_s1_foundation.py -v
```

All tests use temporary directories (`tmp_path` fixture) and mocked HTTP (no real LM Studio
or network calls). Tests must be deterministic and run offline.

### Manual Smoke Test

```bash
# 1. Config loads successfully
python -c "from src.core.config import load_config; c = load_config(); print(c)"

# 2. Missing config field fails fast
echo '{}' > config_bad.json
python -c "from src.core.config import load_config; load_config('config_bad.json')"
# Expected: SystemExit with "Missing required config field: vault_path"

# 3. Directories created
python -c "from src.core.config import load_config; from src.core.dirs import ensure_directories; ensure_directories(load_config())"
# Expected: directories created (or confirmed existing)

# 4. Provider selection
python -c "from src.core.config import load_config; from src.core.provider import select_provider, ensure_provider_ready; c = load_config(); p = select_provider(c); p = ensure_provider_ready(p, c); print(f'Provider: {p}')"
# Expected: prompts if "ask", checks LM Studio if selected, returns provider name
```

---

## ENGINEERING.md Validation Checklist

| Principle              | Satisfied?                                                        |
|------------------------|-------------------------------------------------------------------|
| Explicit > implicit    | All fields typed. Defaults explicit in dataclass. Required fields fail fast. |
| Simple > clever        | Flat JSON. Flat dataclass. No inheritance. No plugin system.      |
| Contracts define behavior | This document. Every API has input/output/raises spec.         |
| Systems fail at boundaries | I-9 boundary fully specified. Validation at load time, not use time. |
| Observable / debuggable | Directory creation logged. Error messages name the specific field/path. |
| Validate all inputs    | Every field has type, range, and nullability constraints. 22 failure test cases. |
| Fail fast and clearly  | `SystemExit(1)` with actionable message on any validation failure. |
| Never swallow errors   | `OSError` propagated. HTTP errors returned as `False`, not ignored. |
| No hardcoded secrets   | API keys in `.env` only. Never logged. Never printed (C-7).      |
