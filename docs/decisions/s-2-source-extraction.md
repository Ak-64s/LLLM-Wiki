# ADR: Source Extraction Pattern

| Field   | Value                                          |
|---------|-------------------------------------------------|
| Slice   | S-2                                             |
| Date    | 2026-04-12                                      |
| Status  | ACCEPTED                                        |
| Decides | How raw sources are converted to text for LLM   |

---

## Context

S-2 is the first slice that handles external I/O beyond a health check: fetching URLs,
reading PDFs, and reading text files. Every downstream slice (S-3 through S-7) consumes
the `(text, metadata)` tuple that S-2 produces. The extraction pattern determines
the API surface, error handling strategy, and extensibility model for all source types.

**Binding constraints:**
- AD-6: OCR via Tesseract, gated behind detection (pdfplumber first).
- AD-10: Raw sources are immutable and stored outside the vault.
- C-11: Tesseract must be installed separately. Tool warns clearly if missing.

**Source types (PROJECT.md):** URL, PDF, plain text/markdown. Three types, all defined
at design time. No user-pluggable source types planned.

---

## Approach 1 — Single dispatch function with internal routing [CHOSEN]

A single public function `extract_source(source: str) -> tuple[str, dict]` detects
the source type from the input string and dispatches to private helpers:
`_extract_url()`, `_extract_pdf()`, `_extract_text()`.

```python
def extract_source(source: str) -> tuple[str, dict]:
    if source.startswith("http://") or source.startswith("https://"):
        return _extract_url(source)
    elif source.lower().endswith(".pdf"):
        return _extract_pdf(source)
    else:
        return _extract_text(source)
```

Callers never need to know the source type. S-3/S-4 call `extract_source()` with
whatever the user provided.

**Strengths:**
- One entry point. Minimal API surface for consumers.
- Detection heuristic is trivial (3 conditions) and fully testable.
- Matches S-1's pattern: flat functions in a single module, no class hierarchy.
- Aligns with ENGINEERING.md: "Simple > clever", "Contracts define behavior."

**Weaknesses:**
- Adding a 4th source type requires an `elif` branch and a new private function.
- Detection relies on string inspection (URL prefix, file extension), which could
  misclassify unusual inputs.

## Approach 2 — Strategy pattern with extractor registry [REJECTED]

An abstract `Extractor` base class with `extract(source) -> tuple[str, dict]`.
Concrete subclasses `UrlExtractor`, `PdfExtractor`, `TextExtractor`. A registry
maps detection rules to extractor instances.

**Why rejected:**
- Three source types, all defined in PROJECT.md, none user-configurable.
  The registry is abstraction for abstraction's sake.
- Adds files, imports, and indirection with no payoff until a 4th source type
  exists (not planned).
- S-1 established the pattern: flat functions, no inheritance. Consistency
  across slices reduces cognitive load.
- Violates ENGINEERING.md: "Simple > clever", "Avoid unnecessary nesting."

---

## Why Approach 1 wins

1. **Minimal API surface.** One function, one return type. Consumers cannot
   misuse it.
2. **Fail-fast on all paths.** Every extractor validates its output (non-empty
   text) and raises `SystemExit` with the source name on failure. No silent
   empty returns.
3. **Adding a 4th type is a small diff.** One `elif`, one function. Not worth
   pre-building an extension framework.
4. **Consistent with S-1.** Flat module, no classes, `_fail()` for errors.
   Same developer experience across the codebase.

---

## Consequences

1. `tools/ingest.py` (S-4+) calls `extract_source(source)` as its first action
   after config loading. Source type is transparent to the caller.
2. Metadata dict (`source`, `method`, `timestamp`, `char_count`) is the contract
   between S-2 and S-3. S-3 uses `char_count` for chunking decisions.
3. OCR is gated behind the 50-char threshold (AD-6). The Tesseract binary
   dependency is surfaced clearly when needed (C-11).
4. URL fetch has explicit timeout (10s connect, 30s read) and size cap (10 MB).
   No automatic retry.

---

## ENGINEERING.md Checklist

| Principle              | Application                                                    |
|------------------------|----------------------------------------------------------------|
| Explicit > implicit    | Source type detection rules enumerated. Method field visible in metadata. |
| Simple > clever        | Single dispatch function. 3 private helpers. No class hierarchy. |
| Contracts define behavior | Contract doc defines every API, boundary, and failure mode. |
| Fail fast and clearly  | `SystemExit` with source name on every failure path. Never returns empty text. |
| Validate all inputs    | Source string validated (non-empty, max length). URL status, PDF content, text content all validated. |
| Never swallow errors   | `requests` exceptions re-raised with context. pdfplumber errors caught with file path. Tesseract missing → actionable install message. |
| Systems fail at boundaries | HTTP boundary: timeout, status, size all specified. File I/O: not-found, permission, encoding all handled. |
