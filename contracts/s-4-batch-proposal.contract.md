# Contract: S-4 Batch Proposal Engine

| Field  | Value                                                         |
|--------|---------------------------------------------------------------|
| Slice  | S-4                                                           |
| Date   | 2026-04-12                                                    |
| Status | DRAFT                                                         |
| Refs   | AD-1, AD-2, AD-7, AD-8, C-1, C-5, C-6, A-4, A-9, A-10     |

---

## APIs

S-4 exposes Python module APIs (no HTTP server). No new outbound HTTP boundaries —
all LLM calls go through S-3's `complete()`. Two modules: `src.core.proposal` (data
structures, slug generation) and `src.core.batch` (orchestration).

### `generate_batch(provider: str, config: Config, env: dict, source_text: str, source_meta: dict) -> list[PageProposal]`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.batch`                                                      |
| Input      | `provider` — `"gemini"` or `"lmstudio"`. `config` — `Config` instance from S-1. `env` — dict from `load_env()`. `source_text` — extracted content from S-2 (non-empty). `source_meta` — metadata dict from S-2 (must contain `"source"` key). |
| Output     | `list[PageProposal]` — ordered list of page proposals. May be empty (valid outcome). |
| Raises     | `SystemExit` on: empty/whitespace-only `source_text`, Phase 1 LLM failure (propagated from `complete()`), unparseable Phase 1 JSON response. |
| Behavior   | 1. Read `index.md` from vault via `_read_index()`. 2. List existing slugs via `_list_existing_slugs()`. 3. **Phase 1 (Plan):** Call `_plan_pages()` — sends index.md + source text to LLM, parses JSON response into page plan list. 4. If plan is empty, return `[]`. 5. **Phase 2 (Generate):** For each planned page, call `_generate_page()` — sends source text + existing page content (if update) + all planned titles to LLM, returns markdown. If Phase 2 fails for a page, print warning and skip it; other pages survive. 6. Build `PageProposal` for each successful generation: generate slug via `slugify()` + `resolve_collision()`, parse conflict markers (if update), populate all fields. 7. Return list of `PageProposal`. |
| Guarantee  | **Never writes to disk.** All output is in-memory (AD-2). |
| Guarantee  | **Partial failure resilient.** A Phase 2 failure for one page does not lose other pages. |
| Idempotent | No. LLM responses are non-deterministic.                             |

### `_plan_pages(provider: str, config: Config, env: dict, source_text: str, index_content: str) -> list[dict]`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.batch` (private)                                            |
| Input      | `provider`, `config`, `env` — forwarded to `complete()`. `source_text` — extracted content. `index_content` — current index.md content (may be `""`). |
| Output     | `list[dict]` — parsed page plan. Each dict contains: `title` (str), `action` (str: `"create"` or `"update"`), `category` (str: `"sources"`, `"entities"`, or `"concepts"`), `existing_page` (str, only for updates — relative path from vault root). |
| Behavior   | 1. Build system prompt instructing LLM to return a JSON array of page plans. 2. Build user content combining index.md content and source text. 3. Call `complete(provider, config, env, system_prompt, user_content)`. 4. Parse response via `_parse_plan_json()`. 5. Return parsed list. |
| Raises     | `SystemExit` propagated from `complete()` on LLM failure. `SystemExit` from `_parse_plan_json()` on invalid response. |

### `_generate_page(provider: str, config: Config, env: dict, source_text: str, page_plan: dict, existing_content: str, all_titles: list[str]) -> str`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.batch` (private)                                            |
| Input      | `provider`, `config`, `env` — forwarded to `complete()`. `source_text` — extracted content. `page_plan` — dict from Phase 1 (title, action, category). `existing_content` — content of existing page (`""` for creates). `all_titles` — list of all planned page titles (for `[[wikilinks]]`). |
| Output     | `str` — generated markdown page content. May contain `⚠️ CONFLICT:` markers for updates. |
| Behavior   | 1. Build system prompt with page title, category, action, and available wikilink targets. 2. Build user content with source text and existing page content (if update). 3. Call `complete(provider, config, env, system_prompt, user_content)`. 4. Return response text. |
| Raises     | `SystemExit` propagated from `complete()` on LLM failure. Caller (`generate_batch`) catches this for partial-failure resilience. |

### `_read_index(vault_path: str) -> str`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.batch` (private)                                            |
| Input      | `vault_path` — from `config.vault_path`.                             |
| Output     | `str` — content of `{vault_path}/wiki/index.md`. Returns `""` if file does not exist. |
| Raises     | Nothing. Missing index.md is a valid state (fresh wiki).             |
| Idempotent | Yes. Pure filesystem read.                                            |

### `_list_existing_slugs(vault_path: str) -> set[str]`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.batch` (private)                                            |
| Input      | `vault_path` — from `config.vault_path`.                             |
| Output     | `set[str]` — set of existing filenames (without `.md` extension) from `{vault_path}/wiki/sources/`, `{vault_path}/wiki/entities/`, `{vault_path}/wiki/concepts/`. Returns `set()` if directories don't exist. |
| Behavior   | Scans all three wiki subdirectories. Collects `.md` filenames with extension stripped. Used for slug collision detection. |
| Idempotent | Yes. Pure filesystem read.                                            |

### `_load_page(vault_path: str, relative_path: str) -> str`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.batch` (private)                                            |
| Input      | `vault_path` — from `config.vault_path`. `relative_path` — relative path from vault root (e.g., `"wiki/concepts/attention.md"`). |
| Output     | `str` — page content. Returns `""` if file does not exist.           |
| Raises     | Nothing. Missing page is handled gracefully (returns empty).         |
| Idempotent | Yes. Pure filesystem read.                                            |

### `_parse_plan_json(raw: str) -> list[dict]`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.batch` (private)                                            |
| Input      | `raw` — LLM response from Phase 1.                                  |
| Output     | `list[dict]` — parsed page plans.                                    |
| Behavior   | 1. Strip markdown code fences (`` ```json ... ``` `` or `` ``` ... ``` ``). 2. Strip any leading/trailing prose outside the JSON array. 3. Parse with `json.loads()`. 4. Validate: must be a list. Each entry must have `"title"` (non-empty str), `"action"` (one of `"create"`, `"update"`), `"category"` (one of `"sources"`, `"entities"`, `"concepts"`). Update entries should have `"existing_page"` (str). 5. Return validated list. |
| Raises     | `SystemExit` on: malformed JSON, not a list, missing `"title"` field, invalid `"action"` value, invalid `"category"` value. Error message names the specific validation failure. |

### `_parse_conflicts(content: str, existing_page: str, source_ref: str) -> list[Conflict]`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.batch` (private)                                            |
| Input      | `content` — generated page markdown (may contain conflict markers). `existing_page` — relative path to the existing page. `source_ref` — source string from metadata. |
| Output     | `list[Conflict]` — extracted conflict objects. Empty list if no markers found. |
| Behavior   | Scans `content` for lines containing `"⚠️ CONFLICT:"`. For each match, extracts the description text after the marker. Builds a `Conflict` with the provided `existing_page` and `source_ref`. Malformed markers (marker with no description) are skipped. |
| Idempotent | Yes. Pure function.                                                   |

### `slugify(title: str) -> str`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.proposal`                                                   |
| Input      | `title` — human-readable page title from LLM.                       |
| Output     | `str` — kebab-case slug. Lowercase, alphanumeric + hyphens only.    |
| Behavior   | 1. Strip leading/trailing whitespace. 2. Lowercase. 3. Replace non-alphanumeric characters (except hyphens) with spaces. 4. Collapse consecutive spaces to single space. 5. Replace spaces with hyphens. 6. Collapse consecutive hyphens to single hyphen. 7. Strip leading/trailing hyphens. |
| Validation | Title must be non-empty after stripping. Must produce a non-empty slug after processing. Raises `ValueError` on violation. |
| Idempotent | Yes. Pure function. Deterministic per AD-7.                          |

### `resolve_collision(slug: str, existing_slugs: set[str]) -> str`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.proposal`                                                   |
| Input      | `slug` — base slug from `slugify()`. `existing_slugs` — set of slugs already in use. |
| Output     | `str` — the original slug if no collision, or `"{slug}-{hash8}"` where `hash8` is the first 8 characters of `hashlib.sha256(slug.encode()).hexdigest()`. |
| Behavior   | If `slug` is not in `existing_slugs`, return it unchanged. Otherwise, append `-{hash8}` suffix. |
| Idempotent | Yes. Pure function. Deterministic per AD-7.                          |

---

## Data Structures

### `PageProposal` (dataclass)

| Field           | Type            | Nullable | Constraints                                  |
|-----------------|-----------------|----------|----------------------------------------------|
| `title`         | `str`           | NO       | Non-empty. LLM-generated human-readable title. Max practical length ~200 chars. |
| `slug`          | `str`           | NO       | Non-empty. Kebab-case. Alphanumeric + hyphens only. Max ~200 chars + 9 (hash suffix). |
| `category`      | `str`           | NO       | One of: `"sources"`, `"entities"`, `"concepts"`. Closed enum. |
| `content`       | `str`           | NO       | Non-empty. Markdown with `[[wikilinks]]` (C-6). May contain `⚠️ CONFLICT:` markers. No max enforced. |
| `action`        | `str`           | NO       | One of: `"create"`, `"update"`. Closed enum. |
| `conflicts`     | `list[Conflict]`| NO       | May be empty list. Empty for `action == "create"`. |
| `existing_path` | `str`           | NO       | Relative path from vault root for updates (e.g., `"wiki/concepts/attention.md"`). Empty string `""` for creates. |

### `Conflict` (dataclass)

| Field           | Type   | Nullable | Constraints                                  |
|-----------------|--------|----------|----------------------------------------------|
| `existing_page` | `str`  | NO       | Relative path to the conflicting existing page. Non-empty. |
| `description`   | `str`  | NO       | LLM-generated description of the contradiction. Non-empty. |
| `source_ref`    | `str`  | NO       | Source citation from S-2 metadata `source` field. Non-empty. |

### Phase 1 JSON Schema (LLM response)

Each entry in the LLM's JSON array response:

| Field           | Type   | Required | Constraints                                  |
|-----------------|--------|----------|----------------------------------------------|
| `title`         | `str`  | YES      | Non-empty. Human-readable page title.        |
| `action`        | `str`  | YES      | One of: `"create"`, `"update"`.              |
| `category`      | `str`  | YES      | One of: `"sources"`, `"entities"`, `"concepts"`. |
| `existing_page` | `str`  | For updates | Relative path from vault root. Required when `action == "update"`. Optional otherwise. |

Example valid response:

```json
[
  {"title": "Attention Is All You Need", "action": "create", "category": "sources"},
  {"title": "Transformer Architecture", "action": "create", "category": "concepts"},
  {"title": "Google DeepMind", "action": "update", "category": "entities", "existing_page": "wiki/entities/google-deepmind.md"}
]
```

### Conflict Marker Format (in LLM-generated content)

```
⚠️ CONFLICT: [description text here]
```

The marker must appear at the start of a line. Everything after `⚠️ CONFLICT: ` on the same line is the description. Markers remain in `PageProposal.content` — they are not stripped. `_parse_conflicts` extracts them as structured `Conflict` objects for S-5's resolution UI.

### Valid Categories

| Category     | Vault subdirectory        | Purpose                                    |
|--------------|---------------------------|--------------------------------------------|
| `"sources"`  | `vault/wiki/sources/`     | One summary page per ingested source.      |
| `"entities"` | `vault/wiki/entities/`    | Named entities (people, orgs, models).     |
| `"concepts"` | `vault/wiki/concepts/`    | Abstract topics or concepts.               |

### Valid Actions

| Action     | Semantics                                                           |
|------------|---------------------------------------------------------------------|
| `"create"` | New page. No existing page. `conflicts` is empty. `existing_path` is `""`. |
| `"update"` | Modify existing page. Existing content loaded for context. Conflicts may be detected. |

### Internal Constants

| Constant              | Type   | Value                    | Rationale                              |
|-----------------------|--------|--------------------------|----------------------------------------|
| `_VALID_CATEGORIES`   | `tuple`| `("sources", "entities", "concepts")` | Closed set. Maps to vault subdirs. |
| `_VALID_ACTIONS`      | `tuple`| `("create", "update")`   | Closed set per backlog spec.           |
| `_CONFLICT_MARKER`    | `str`  | `"⚠️ CONFLICT:"`         | Delimiter for contradiction markers.   |

---

## Boundary Limits

| Boundary                              | Limit                 | Rationale                                          |
|---------------------------------------|-----------------------|----------------------------------------------------|
| `source_text` length                  | Must be non-empty     | Empty source has nothing to synthesize.            |
| Phase 1 JSON response                 | Must be valid JSON array | LLM output is untrusted. Validated strictly.     |
| Phase 1 plan entries                  | Each must have title, action, category | Incomplete entries cannot produce valid proposals. |
| Category values                       | Closed enum: 3 values | Maps directly to vault directory structure.        |
| Action values                         | Closed enum: 2 values | Only create and update are supported in MVP.       |
| Slug length                           | No enforced max       | Practical limit ~200 chars from title. Filesystem limits (~255 chars) are the ceiling. |
| Page count per batch                  | No enforced max       | Bounded by A-10 (~15 pages). LLM naturally limits output. |
| Phase 2 per-page LLM timeout          | Inherited from S-3    | Gemini: 30s/120s. LM Studio: 30s/300s.            |
| Conflict markers per page             | No enforced max       | All detected markers are extracted.                |
| index.md size                         | No enforced max       | Read into memory. Practical limit is A-4 (~300 pages). |

No new rate limits are introduced by S-4. LLM rate limits are governed by S-3/L-8.
No retry/backoff. Phase 2 failures are skipped, not retried.

---

## Tests

Execution method: `pytest tests/unit/test_s4_batch.py -v`

Dependencies: `pytest`. All LLM calls are mocked via `unittest.mock.patch` on
`src.core.llm.complete`. Filesystem access is mocked via `tmp_path` fixture or
`unittest.mock.patch`. Tests must be deterministic and run offline. No real
LLM calls.

### Slug Generation (proposal.py)

#### Happy Path

| ID     | Test                                       | Input                                   | Expected                                        |
|--------|--------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-4.01 | Simple title produces kebab-case slug     | `"Attention Mechanism"`                  | `slugify()` returns `"attention-mechanism"`.     |
| T-4.02 | Special characters stripped                | `"Hello, World! (2024)"`                | Returns `"hello-world-2024"`.                    |
| T-4.03 | No collision returns original slug        | `slug="foo"`, `existing=set()`           | `resolve_collision()` returns `"foo"`.           |
| T-4.04 | Collision appends SHA256 hash             | `slug="foo"`, `existing={"foo"}`         | Returns `"foo-{sha256[:8]}"`. Deterministic.     |

#### Edge Cases

| ID     | Test                                       | Input                                   | Expected                                        |
|--------|--------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-4.05 | Mixed case lowercased                     | `"GPT-4 Architecture"`                  | Returns `"gpt-4-architecture"`.                  |
| T-4.06 | Multiple spaces/hyphens collapsed         | `"hello   --  world"`                   | Returns `"hello-world"`.                         |
| T-4.07 | Title with numbers preserved              | `"Llama 3.1 70B"`                       | Returns `"llama-31-70b"` (dot stripped).         |
| T-4.08 | Same title produces same slug             | Call `slugify("Test Title")` twice       | Both return identical result. Deterministic.     |

#### Failure Cases

| ID     | Test                                       | Input                                   | Expected                                        |
|--------|--------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-4.09 | Empty title                               | `""`                                     | `ValueError`.                                    |
| T-4.10 | Whitespace-only title                     | `"   \t  "`                             | `ValueError`.                                    |
| T-4.11 | Title with only special chars             | `"!@#$%^&*()"`                          | `ValueError` (produces empty slug).              |

### Wiki State Reading (batch.py)

#### Happy Path

| ID     | Test                                       | Input                                   | Expected                                        |
|--------|--------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-4.12 | _read_index reads existing index.md       | `tmp_path` with `wiki/index.md` containing `"# Index"` | Returns `"# Index"`.                            |
| T-4.13 | _list_existing_slugs finds slugs          | `tmp_path` with `wiki/concepts/foo.md` and `wiki/entities/bar.md` | Returns `{"foo", "bar"}`.                       |

#### Edge Cases

| ID     | Test                                       | Input                                   | Expected                                        |
|--------|--------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-4.14 | _read_index returns "" for missing file   | `tmp_path` with no `wiki/index.md`       | Returns `""`.                                    |
| T-4.15 | _list_existing_slugs returns empty set    | `tmp_path` with no wiki subdirs          | Returns `set()`.                                 |

### Phase 1 JSON Parsing (_parse_plan_json)

#### Happy Path

| ID     | Test                                       | Input                                   | Expected                                        |
|--------|--------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-4.16 | Valid JSON array parsed                   | `'[{"title":"Foo","action":"create","category":"concepts"}]'` | Returns list with one dict, fields validated.    |
| T-4.17 | Markdown code fences stripped             | `` '```json\n[{"title":"Foo","action":"create","category":"concepts"}]\n```' `` | Returns parsed list. Fences removed before parsing. |

#### Edge Cases

| ID     | Test                                       | Input                                   | Expected                                        |
|--------|--------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-4.18 | Empty JSON array                          | `"[]"`                                   | Returns `[]`.                                    |
| T-4.19 | Leading/trailing prose stripped            | `"Here is the plan:\n[...]\nLet me know"` | JSON array extracted and parsed.                 |

#### Failure Cases

| ID     | Test                                       | Input                                   | Expected                                        |
|--------|--------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-4.20 | Malformed JSON                            | `"not json at all"`                      | `SystemExit`. Message contains `"JSON"`.         |
| T-4.21 | JSON is object, not array                 | `'{"title":"Foo"}'`                      | `SystemExit`. Message contains `"array"`.        |
| T-4.22 | Missing title field                       | `'[{"action":"create","category":"concepts"}]'` | `SystemExit`. Message contains `"title"`.        |
| T-4.23 | Invalid category value                    | `'[{"title":"Foo","action":"create","category":"invalid"}]'` | `SystemExit`. Message contains `"category"`.     |

### Conflict Parsing (_parse_conflicts)

#### Happy Path

| ID     | Test                                       | Input                                   | Expected                                        |
|--------|--------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-4.24 | Extracts single conflict marker           | Content with one `⚠️ CONFLICT: Old says X, new says Y` line | Returns 1 `Conflict`. Description = `"Old says X, new says Y"`. |

#### Edge Cases

| ID     | Test                                       | Input                                   | Expected                                        |
|--------|--------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-4.25 | No conflict markers                       | Plain markdown with no markers           | Returns `[]`.                                    |
| T-4.26 | Multiple conflict markers                 | Content with 3 `⚠️ CONFLICT:` lines     | Returns 3 `Conflict` objects.                    |
| T-4.27 | Marker with no description skipped        | Content with `⚠️ CONFLICT:` followed by empty/whitespace | Returns `[]` (skipped).                          |

### Batch Generation (generate_batch)

#### Happy Path

| ID     | Test                                       | Input                                   | Expected                                        |
|--------|--------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-4.28 | Fresh wiki returns create proposals       | Mock Phase 1 returning 2 pages. Mock Phase 2 returning content. Empty wiki (`tmp_path`). | Returns 2 `PageProposal` with `action="create"`, valid slugs, non-empty content. |
| T-4.29 | Existing wiki returns create+update mix   | Mock Phase 1 returning 1 create + 1 update. Existing page in `tmp_path`. Mock Phase 2. | Returns 2 proposals: one create, one update. Update has `existing_path` populated. |
| T-4.30 | Update with conflict markers detected     | Mock Phase 2 returning content with `⚠️ CONFLICT:` line. | Update proposal has non-empty `conflicts` list.  |
| T-4.31 | All proposal fields populated correctly   | Mock both phases.                        | Each proposal has: non-empty title, slug, category, content, valid action, list conflicts, correct existing_path. |

#### Edge Cases

| ID     | Test                                       | Input                                   | Expected                                        |
|--------|--------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-4.32 | Empty plan returns []                     | Mock Phase 1 returning `"[]"`.           | Returns `[]`. No Phase 2 calls made.             |
| T-4.33 | Phase 2 failure skips page, others survive | Mock Phase 1 returning 3 pages. Mock Phase 2 raising `SystemExit` on 2nd, succeeding on others. | Returns 2 proposals. Warning printed for failed page. |
| T-4.34 | Slug collision among new pages resolved   | Mock Phase 1 returning 2 pages with same title. | Second page gets hash-suffixed slug.             |
| T-4.35 | Slug collision with existing page resolved | Existing `foo.md` in wiki. Mock Phase 1 returning page with title that slugifies to `"foo"`. | Proposal slug gets hash-suffixed.                |
| T-4.36 | Create proposal has empty conflicts/path  | Mock Phase 1 with `action="create"`.     | `conflicts == []`, `existing_path == ""`.        |

#### Failure Cases

| ID     | Test                                       | Input                                   | Expected                                        |
|--------|--------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-4.37 | Phase 1 LLM failure propagated            | Mock `complete()` raising `SystemExit`.  | `SystemExit` propagated. No partial batch.       |
| T-4.38 | Empty source_text                         | `source_text=""`                         | `SystemExit`. Message contains `"empty"`.        |
| T-4.39 | Whitespace-only source_text               | `source_text="   \n  "`                 | `SystemExit`. Message contains `"empty"`.        |
| T-4.40 | Update target page not found on disk      | Mock Phase 1 with update pointing to nonexistent page. | Page generation proceeds with `existing_content=""`. Warning printed. |

---

## Execution Method

### Unit Tests

```bash
pip install -r requirements.txt
pip install pytest
pytest tests/unit/test_s4_batch.py -v
```

All tests mock LLM calls via `unittest.mock.patch` on `src.core.llm.complete`:
- Phase 1: Mock `complete()` to return predefined JSON strings.
- Phase 2: Mock `complete()` to return predefined markdown strings.
- Slug generation: pure function tests. No mocking needed.
- Wiki state reading: uses `tmp_path` fixture for real temp directories.

Tests must be deterministic and run offline. No real LLM calls.

### Manual Smoke Test

```bash
# 1. Slug generation
python -c "
from src.core.proposal import slugify, resolve_collision
print(slugify('Attention Is All You Need'))
print(resolve_collision('foo', {'foo', 'bar'}))
"
# Expected: attention-is-all-you-need, foo-{hash}

# 2. Full batch generation (requires LLM provider running)
python -c "
from src.core.config import load_config, load_env
from src.core.extract import extract_source
from src.core.batch import generate_batch
config = load_config()
env = load_env(config.default_provider)
text, meta = extract_source('README.md')
batch = generate_batch(config.default_provider, config, env, text, meta)
for p in batch:
    print(f'{p.action}: {p.title} -> {p.category}/{p.slug}.md')
"

# 3. Empty source fails fast
python -c "
from src.core.config import load_config, load_env
from src.core.batch import generate_batch
generate_batch('gemini', load_config(), {}, '', {'source': 'test'})
"
# Expected: SystemExit with "empty"
```

---

## ENGINEERING.md Validation Checklist

| Principle              | Satisfied?                                                        |
|------------------------|-------------------------------------------------------------------|
| Explicit > implicit    | Two-phase pipeline makes plan vs. generate distinction explicit. Categories and actions are closed enums. Slug generation is deterministic. Conflict markers are a defined format. |
| Simple > clever        | Flat functions. Two modules (data + orchestration). No class hierarchy. No strategy pattern. |
| Contracts define behavior | This document. Every API has input/output/raises spec. Phase 1 JSON schema defined. Conflict marker format defined. |
| Systems fail at boundaries | Phase 1 JSON validated strictly. LLM responses never trusted. Missing files handled gracefully. |
| Observable / debuggable | Phase 2 failures print warnings naming the failed page. Error messages from JSON parsing name the specific field. Conflict markers are visible in page content. |
| Validate all inputs    | `source_text` validated (non-empty). Phase 1 JSON validated (array, required fields, enum values). Categories and actions validated against closed sets. Slugs validated (non-empty after processing). |
| Fail fast and clearly  | `SystemExit` on Phase 1 failure. `ValueError` on invalid slug input. Empty source caught before LLM call. |
| Never swallow errors   | Phase 2 failures are printed as warnings (not silently dropped). JSON parse errors include the specific issue. |
| No hardcoded secrets   | API key handled by S-3. S-4 passes `env` through. Never logged. |
| Treat inputs as untrusted | LLM Phase 1 JSON is validated field-by-field. LLM Phase 2 markdown is not structurally trusted — conflict markers are best-effort extraction. Missing pages on disk return "" instead of crashing. |
