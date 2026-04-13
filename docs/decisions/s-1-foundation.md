# ADR: Foundation Config Loading Pattern

| Field   | Value                                |
|---------|--------------------------------------|
| Slice   | S-1                                  |
| Date    | 2026-04-12                           |
| Status  | ACCEPTED                             |
| Decides | Config loading and validation pattern|

---

## Context

S-1 is the first code slice. Every subsequent slice imports from `src.core` to load
config, select a provider, and initialize directories. The config loading pattern is the
single most-imported contract in the system (boundary I-9).

The decision: how config.json is loaded, validated, and exposed to the rest of the codebase.

**Binding constraints:**
- C-7: API keys in `.env` or env vars, never in source or config.
- C-8: Sources directory must be outside the vault.
- C-10: Chunk thresholds configurable in config.json.

---

## Approach 1 — Typed dataclass with validation at load time [CHOSEN]

A `Config` dataclass defines all fields with types and defaults. `load_config()` reads
JSON, validates required fields, checks types and ranges, and returns a `Config` instance
or calls `sys.exit(msg)` with an actionable error message naming the specific field.

```python
@dataclass
class Config:
    vault_path: str = ""
    sources_path: str = ""
    default_provider: str = "gemini"
    chunk_threshold_lmstudio: int = 4000
    # ... all fields typed with defaults
```

Callers access `config.vault_path` with IDE autocomplete and type safety. Validation runs
once at load time — no downstream code needs to re-check.

**Strengths:**
- Single point of validation. Fail fast at startup, not mid-ingest.
- Typed access prevents typo-based bugs (`config.valut_path` is a static error).
- Defaults explicit in the dataclass definition. No hidden fallbacks.
- Aligns with ENGINEERING.md: "contracts define behavior", "validate all inputs",
  "fail fast and clearly".

**Weaknesses:**
- Slightly more boilerplate than raw dict access.
- Adding a field requires updating the dataclass and validation.

## Approach 2 — Plain dict, validated ad-hoc [REJECTED]

`json.load()` returns a raw `dict`. Each consumer checks for the keys it needs at point
of use. No central schema.

```python
config = json.load(open("config.json"))
vault = config.get("vault_path", "vault")  # default hidden at use site
```

**Why rejected:**
- Validation is scattered. Missing-key errors surface late (during ingest, not at startup).
- No central schema — the "contract" is implicit across all consumers.
- Defaults hidden at each call site. Two consumers can disagree on the default for the
  same field.
- Violates ENGINEERING.md: "define strict input/output schemas", "fail fast", "single
  source of truth".

---

## Why Approach 1 wins

1. **Fail fast.** A missing `vault_path` is caught before any source extraction or LLM
   call, not 30 seconds into an ingest session.
2. **Single source of truth.** The `Config` dataclass is the schema. Defaults are defined
   once. No scattered `.get()` calls with divergent fallbacks.
3. **Testable.** 22 failure test cases validate every field constraint. Each test is
   deterministic and runs offline.
4. **Low cost.** The dataclass is ~10 lines. Validation is ~60 lines. Total implementation
   is under 130 lines including all boundary checks.

---

## Consequences

1. All tools (`ingest.py`, `lint.py`, `build_graph.py`, `query.py`) import `load_config()`
   from `src.core.config` as their first action.
2. Adding a config field requires: add to dataclass, add validation rule, add test case.
3. The `Config` dataclass is the contract for boundary I-9. Downstream slices depend on
   its field names and types.
4. `load_env(provider)` accepts the selected provider. `GEMINI_API_KEY` is only required
   when `provider == "gemini"`. LM-Studio-only users are not blocked by a missing Gemini key.

## Post-audit amendments (2026-04-12)

Three implementation defects were identified during Staff Engineer audit and fixed:

1. **TOCTOU race in `ensure_directories`** — `if not exists() → makedirs()` replaced with
   `os.makedirs(exist_ok=True)`. Eliminates race between check and create.
2. **C-8 path comparison case-sensitive on Windows** — `str.startswith()` replaced with
   `os.path.commonpath()` + `os.path.normcase()`. Handles Windows case-insensitive paths.
3. **`load_env()` unconditionally required `GEMINI_API_KEY`** — signature changed to
   `load_env(provider="gemini")`. Key is only enforced when Gemini is the active provider.

No tracked assumptions (A-1 through A-12) were invalidated. These were implementation bugs,
not design-level failures.

---

## ENGINEERING.md Checklist

| Principle              | Application                                                    |
|------------------------|----------------------------------------------------------------|
| Explicit > implicit    | All fields typed. Defaults in dataclass, not at use sites.     |
| Simple > clever        | Flat JSON. Flat dataclass. No inheritance.                     |
| Contracts define behavior | Config dataclass + contract doc define the I-9 boundary.    |
| Fail fast and clearly  | `sys.exit(msg)` with field name on any validation failure.     |
| Validate all inputs    | Type, range, nullability checks for every field.               |
| Never swallow errors   | OSError propagated. Missing fields named explicitly.           |
