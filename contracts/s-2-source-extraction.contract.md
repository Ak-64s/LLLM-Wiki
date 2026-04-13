# Contract: S-2 Source Extraction

| Field  | Value                                                         |
|--------|---------------------------------------------------------------|
| Slice  | S-2                                                           |
| Date   | 2026-04-12                                                    |
| Status | DRAFT                                                         |
| Refs   | AD-6, AD-10, C-1, C-11, A-5, A-6                            |

---

## APIs

S-2 exposes Python module APIs (no HTTP server). One outbound HTTP boundary exists: URL
fetching for web sources.

### `extract_source(source: str) -> tuple[str, dict]`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.extract`                                                    |
| Input      | `source` — a URL (`http://` or `https://` prefix) or a filesystem path to a local file (`.pdf`, `.txt`, `.md`, or any other text file). Max length: 2048 chars. |
| Output     | `tuple[str, dict]` — `(text, metadata)`. `text` is the extracted content (always non-empty after `strip()`). `metadata` schema defined below. |
| Raises     | `SystemExit` with message naming the source on any unrecoverable failure. |
| Dispatch   | Detects source type from input string. URL if starts with `http://` or `https://`. PDF if path ends with `.pdf` (case-insensitive). Text file otherwise. |
| Guarantee  | **Never returns empty text.** If extraction produces empty/whitespace-only text after stripping, raises `SystemExit` with message: `"Extraction produced no text from '{source}'."` |
| Idempotent | Yes for local files (pure read). URL fetch may return different content on repeated calls. |
| Side effects | None. Reads only. Never writes to any file (AD-10). |

### `_extract_url(url: str) -> tuple[str, dict]`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.extract` (private)                                          |
| Input      | `url` — a URL string starting with `http://` or `https://`.          |
| Output     | `(text, metadata)` where `text` is the visible text content of the page, HTML stripped. `metadata.method` is `"url"`. |
| Behavior   | 1. Send HTTP GET to `url` with timeout. 2. Validate response status is 200. 3. Parse HTML body with BeautifulSoup. 4. Extract visible text, stripping `<script>`, `<style>`, `<nav>`, `<footer>`, `<header>` tags. 5. Collapse whitespace. |
| Raises     | `SystemExit` with message naming the URL and failure reason on: connection error, timeout, DNS failure, non-200 status, or empty extraction. |
| Boundary   | **Outbound HTTP** — see HTTP boundary spec below.                    |

#### HTTP Boundary: URL Fetch

| Aspect         | Spec                                                        |
|----------------|-------------------------------------------------------------|
| Method         | `GET`                                                       |
| URL            | User-provided URL (validated to start with `http(s)://`)   |
| Request body   | None                                                        |
| Headers        | `User-Agent: llm-wiki/0.1` (identify as a bot; avoid silent blocks) |
| Expected 200   | HTML body. Content-Type not strictly validated — we attempt parse regardless. |
| Expected !200  | Any non-200 status → `SystemExit` with message: `"URL returned HTTP {status}: '{url}'."` |
| Connection err | `requests.ConnectionError` → `SystemExit`: `"Cannot connect to URL: '{url}'."` |
| DNS failure    | `requests.ConnectionError` (subset) → same handling as connection error. |
| Timeout        | `requests.Timeout` → `SystemExit`: `"URL request timed out: '{url}'."` |
| Other          | `requests.RequestException` → `SystemExit`: `"URL request failed: '{url}': {error}"` |
| Timeout values | Connect: 10s. Read: 30s.                                   |
| Retry          | No automatic retry. Caller can re-invoke.                   |
| Max response   | 10 MB. Responses larger than 10 MB → `SystemExit`: `"Response too large (>10 MB): '{url}'."` Checked via `Content-Length` header when present; otherwise streamed with size tracking. |

### `_extract_pdf(path: str) -> tuple[str, dict]`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.extract` (private)                                          |
| Input      | `path` — filesystem path to a `.pdf` file.                           |
| Output     | `(text, metadata)` where `text` is extracted PDF content. `metadata.method` is `"pdf_text"` for text-native PDFs, `"pdf_ocr"` for OCR-processed PDFs. |
| Behavior   | 1. Open PDF with pdfplumber. 2. Extract text from all pages, concatenated with page breaks. 3. If total `len(text.strip())` < `_MIN_PDF_CHARS` (50): assume scanned/image PDF → invoke OCR fallback. 4. OCR fallback: print `"Scanned PDF detected. Running OCR..."` to stdout, then invoke `pytesseract.image_to_string()` on each page rendered as image. |
| Raises     | `SystemExit` naming the file path on: file not found, corrupt/invalid PDF, pdfplumber error. |
|            | `SystemExit` with message: `"Tesseract is not installed. Install it from https://github.com/tesseract-ocr/tesseract and ensure it is on your PATH (C-11)."` if Tesseract is missing and OCR is needed. |
| AD-6       | OCR is gated behind detection. pdfplumber is always tried first. User is notified when OCR triggers. |
| C-11       | Tesseract is an external binary. Missing binary produces an actionable error, not a stack trace. |

### `_extract_text(path: str) -> tuple[str, dict]`

| Aspect     | Spec                                                                  |
|------------|-----------------------------------------------------------------------|
| Module     | `src.core.extract` (private)                                          |
| Input      | `path` — filesystem path to a text or markdown file.                 |
| Output     | `(text, metadata)` where `text` is the file content. `metadata.method` is `"text"`. |
| Behavior   | 1. Read file with `Path.read_text(encoding="utf-8")`. 2. If file has a UTF-8 BOM, it is stripped automatically by Python's `utf-8-sig` handling (we use `utf-8-sig` as encoding). |
| Raises     | `SystemExit` naming the file path on: file not found, permission error, encoding error (non-UTF-8 file). |

---

## Data Structures

### Extraction Metadata (`dict`)

Returned as the second element of every `extract_source()` call.

| Field             | Type   | Nullable | Constraints                                  |
|-------------------|--------|----------|----------------------------------------------|
| `source`          | `str`  | NO       | Original source string as passed by caller. Max 2048 chars. |
| `method`          | `str`  | NO       | One of: `"url"`, `"pdf_text"`, `"pdf_ocr"`, `"text"`. Closed enum. |
| `timestamp`       | `str`  | NO       | ISO 8601 UTC timestamp of extraction. Format: `YYYY-MM-DDTHH:MM:SSZ`. |
| `char_count`      | `int`  | NO       | `len(text)` of extracted content. Always > 0. |

Nullability: No field is nullable. All fields have concrete values after extraction completes.

No dataclass is used for metadata. A plain `dict` is sufficient because:
- The metadata is write-once, read-once (passed to S-3 and logged).
- No downstream code accesses it by attribute.
- Adding fields later is a dict key addition, not a schema migration.

### Source Type Detection Rules

| Condition                                       | Detected type | Handler           |
|-------------------------------------------------|---------------|-------------------|
| `source.startswith("http://")` or `source.startswith("https://")` | URL   | `_extract_url`    |
| `source.lower().endswith(".pdf")`               | PDF           | `_extract_pdf`    |
| Everything else                                 | Text file     | `_extract_text`   |

Evaluation order: URL check first, then PDF extension, then text fallback.

### Internal Constants

| Constant            | Type  | Value   | Rationale                                          |
|---------------------|-------|---------|----------------------------------------------------|
| `_CONNECT_TIMEOUT`  | `int` | `10`    | Generous for slow DNS. Fail within human patience. |
| `_READ_TIMEOUT`     | `int` | `30`    | Large pages may be slow. 30s is the upper bound.   |
| `_MAX_RESPONSE_SIZE`| `int` | `10_485_760` | 10 MB. Protects against unbounded downloads.  |
| `_MIN_PDF_CHARS`    | `int` | `50`    | Below this, text extraction is considered failed (scanned PDF). |
| `_STRIPPED_TAGS`     | `list[str]` | `["script", "style", "nav", "footer", "header"]` | Non-content HTML tags removed before text extraction. |

---

## Boundary Limits

| Boundary                      | Limit               | Rationale                                          |
|-------------------------------|----------------------|----------------------------------------------------|
| Source string length          | 2048 chars max       | Standard URL limit. Local paths well under this.   |
| URL fetch connect timeout     | 10 seconds           | Generous for DNS + TCP handshake.                  |
| URL fetch read timeout        | 30 seconds           | Large pages. Hard ceiling on wait.                 |
| URL response body size        | 10 MB max            | Protects against unbounded downloads. Most articles are <1 MB. |
| PDF file size                 | No enforced max      | pdfplumber handles large PDFs page-by-page. OS and memory are the ceiling. |
| Text file size                | No enforced max      | `Path.read_text()` loads into memory. Practical limit is available RAM. |
| OCR char threshold            | 50 chars min         | Below this, pdfplumber result is treated as "extraction failed." |
| Metadata `source` field       | 2048 chars max       | Matches source string limit.                       |
| Extracted text                | Must be non-empty    | `len(text.strip()) > 0` enforced. Empty → `SystemExit`. |

No rate limits apply to S-2. No latency targets for MVP. URL fetch latency bounded by
timeout values. PDF/text extraction latency is I/O-bound and not capped.

---

## Tests

Execution method: `pytest tests/unit/test_s2_extraction.py -v`

Dependencies: `pytest`, `requests`, `beautifulsoup4`, `pdfplumber`. External services
(URLs, Tesseract) are mocked. Tests must be deterministic and run offline.

### URL Extraction

#### Happy Path

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-2.01 | Extract text from valid HTML page          | Mock URL returning `<html><body><p>Hello world</p></body></html>` | `text == "Hello world"`, `metadata["method"] == "url"`, `metadata["char_count"] == 11` |
| T-2.02 | Script and style tags stripped             | Mock URL returning HTML with `<script>` and `<style>` blocks alongside `<p>Content</p>` | `text` contains `"Content"`, does not contain script/style text |
| T-2.03 | Nav, footer, header tags stripped          | Mock URL returning HTML with `<nav>`, `<footer>`, `<header>` blocks alongside `<main>Text</main>` | `text` contains `"Text"`, does not contain nav/footer/header text |
| T-2.04 | Metadata fields populated correctly        | Mock URL returning valid HTML            | `metadata["source"]` equals the URL, `metadata["method"] == "url"`, `metadata["timestamp"]` is valid ISO 8601, `metadata["char_count"] > 0` |

#### Edge Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-2.05 | HTML with no body tag                      | Mock URL returning `<html>Plain text only</html>` | Extracts `"Plain text only"`. Does not crash.  |
| T-2.06 | Whitespace collapsing                      | Mock URL returning `<p>  lots   of    spaces  </p>` | `text` has single spaces between words.        |
| T-2.07 | Response exactly at 10 MB limit            | Mock URL with `Content-Length: 10485760` | Extraction proceeds. No size error.             |

#### Failure Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-2.08 | URL unreachable (connection error)         | Mock `requests.ConnectionError`          | `SystemExit`. Message contains the URL and "Cannot connect". |
| T-2.09 | URL timeout                                | Mock `requests.Timeout`                  | `SystemExit`. Message contains the URL and "timed out". |
| T-2.10 | URL returns 404                            | Mock response with `status_code=404`     | `SystemExit`. Message contains `"HTTP 404"` and the URL. |
| T-2.11 | URL returns 500                            | Mock response with `status_code=500`     | `SystemExit`. Message contains `"HTTP 500"` and the URL. |
| T-2.12 | URL response exceeds 10 MB                 | Mock URL with `Content-Length: 20000000` | `SystemExit`. Message contains `"too large"` and the URL. |
| T-2.13 | URL returns empty page                     | Mock URL returning `<html><body></body></html>` | `SystemExit`. Message contains `"no text"` and the URL. |

### PDF Extraction

#### Happy Path

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-2.14 | Extract text from text-native PDF          | Mock pdfplumber returning 500 chars of text | `text` contains the extracted content, `metadata["method"] == "pdf_text"` |
| T-2.15 | OCR triggered on scanned PDF               | Mock pdfplumber returning `""` (0 chars), mock pytesseract returning `"OCR text"` | `text == "OCR text"`, `metadata["method"] == "pdf_ocr"` |
| T-2.16 | OCR notification printed                   | Mock pdfplumber returning `""`, mock pytesseract returning text | stdout contains `"Scanned PDF detected"` |
| T-2.17 | Multi-page PDF concatenation               | Mock pdfplumber with 3 pages of text     | All 3 pages appear in `text`, separated by newlines |

#### Edge Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-2.18 | PDF with exactly 50 chars (threshold boundary) | Mock pdfplumber returning exactly 50 chars | `metadata["method"] == "pdf_text"`. OCR is NOT triggered. |
| T-2.19 | PDF with 49 chars (below threshold)        | Mock pdfplumber returning 49 chars       | OCR IS triggered. `metadata["method"] == "pdf_ocr"`. |
| T-2.20 | PDF path with spaces                       | Temp file at `"/tmp/my file.pdf"`        | Extraction proceeds. No path error.             |

#### Failure Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-2.21 | PDF file not found                         | Non-existent path `"/nonexistent/file.pdf"` | `SystemExit`. Message contains the file path and "not found". |
| T-2.22 | Corrupt PDF                                | Temp file with random bytes, `.pdf` extension | `SystemExit`. Message contains the file path.   |
| T-2.23 | Tesseract not installed (OCR needed)       | Mock pdfplumber returning `""`, mock pytesseract raising `TesseractNotFoundError` | `SystemExit`. Message contains `"Tesseract"` and `"C-11"`. |
| T-2.24 | PDF + OCR both produce empty text          | Mock pdfplumber returning `""`, mock pytesseract returning `""` | `SystemExit`. Message contains `"no text"` and the file path. |

### Text / Markdown Extraction

#### Happy Path

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-2.25 | Extract text from .txt file                | Temp file with `"Hello world"` content   | `text == "Hello world"`, `metadata["method"] == "text"` |
| T-2.26 | Extract text from .md file                 | Temp file with markdown content          | `text` matches file content, `metadata["method"] == "text"` |
| T-2.27 | Metadata fields populated correctly        | Temp file with content                   | `metadata["source"]` equals the path, `metadata["timestamp"]` is valid ISO 8601, `metadata["char_count"]` matches `len(text)` |

#### Edge Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-2.28 | File with UTF-8 BOM                        | Temp file written with BOM prefix        | BOM stripped. `text` does not start with `\ufeff`. |
| T-2.29 | File path with spaces                      | Temp file at path containing spaces      | Extraction proceeds. No path error.             |
| T-2.30 | File with only whitespace content          | Temp file with `"   \n\t  "`            | `SystemExit`. Message contains `"no text"`.     |

#### Failure Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-2.31 | Text file not found                        | Non-existent path `"/nonexistent/file.txt"` | `SystemExit`. Message contains the file path and "not found". |
| T-2.32 | Permission error on text file              | Temp file with read permission removed (skip on Windows) | `SystemExit`. Message contains the file path.   |
| T-2.33 | Non-UTF-8 encoded file                     | Temp file written with `latin-1` encoding containing non-ASCII bytes | `SystemExit`. Message contains the file path and "encoding". |

### Dispatch Logic

#### Happy Path

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-2.34 | URL detected from http:// prefix           | `"http://example.com"` (mocked)          | Dispatches to URL extractor. `metadata["method"] == "url"`. |
| T-2.35 | URL detected from https:// prefix          | `"https://example.com"` (mocked)         | Dispatches to URL extractor. `metadata["method"] == "url"`. |
| T-2.36 | PDF detected from .pdf extension           | Temp `.pdf` file (mocked pdfplumber)     | Dispatches to PDF extractor. `metadata["method"]` starts with `"pdf"`. |
| T-2.37 | Text fallback for .txt file                | Temp `.txt` file                         | Dispatches to text extractor. `metadata["method"] == "text"`. |
| T-2.38 | Text fallback for .md file                 | Temp `.md` file                          | Dispatches to text extractor. `metadata["method"] == "text"`. |
| T-2.39 | Text fallback for extensionless file       | Temp file with no extension              | Dispatches to text extractor. `metadata["method"] == "text"`. |

#### Edge Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-2.40 | PDF extension case-insensitive             | Temp file with `.PDF` extension (mocked pdfplumber) | Dispatches to PDF extractor.                    |
| T-2.41 | URL with .pdf in path                      | `"https://example.com/doc.pdf"` (mocked) | Dispatches to **URL** extractor (URL prefix takes priority). |

#### Failure Cases

| ID     | Test                                        | Input                                   | Expected                                        |
|--------|---------------------------------------------|-----------------------------------------|-------------------------------------------------|
| T-2.42 | Empty source string                        | `""`                                     | `SystemExit`. Message: source must be non-empty. |
| T-2.43 | Source string exceeds 2048 chars           | `"x" * 2049`                            | `SystemExit`. Message: source too long.          |

---

## Execution Method

### Unit Tests

```bash
pip install -r requirements.txt
pip install pytest
pytest tests/unit/test_s2_extraction.py -v
```

All tests mock external dependencies:
- URL extraction: `requests.get` is mocked via `unittest.mock.patch`. No real HTTP calls.
- PDF extraction: `pdfplumber.open` is mocked. No real PDF files needed for most tests
  (corrupt PDF test uses a temp file with random bytes).
- OCR: `pytesseract.image_to_string` is mocked. Tesseract binary is never invoked.
- Text extraction: uses `tmp_path` fixture for real temp files.

Tests must be deterministic and run offline.

### Manual Smoke Test

```bash
# 1. Extract from a local text file
python -c "
from src.core.extract import extract_source
text, meta = extract_source('README.md')
print(f'Method: {meta[\"method\"]}, Chars: {meta[\"char_count\"]}')
print(text[:200])
"

# 2. Extract from a URL (requires internet)
python -c "
from src.core.extract import extract_source
text, meta = extract_source('https://example.com')
print(f'Method: {meta[\"method\"]}, Chars: {meta[\"char_count\"]}')
print(text[:200])
"

# 3. Verify empty source fails fast
python -c "from src.core.extract import extract_source; extract_source('')"
# Expected: SystemExit with "source must be non-empty"

# 4. Verify missing file fails fast
python -c "from src.core.extract import extract_source; extract_source('/nonexistent/file.txt')"
# Expected: SystemExit with file path and "not found"
```

---

## ENGINEERING.md Validation Checklist

| Principle              | Satisfied?                                                        |
|------------------------|-------------------------------------------------------------------|
| Explicit > implicit    | Source type detection rules are enumerated. Method field in metadata makes extraction type visible. |
| Simple > clever        | Single dispatch function. No class hierarchy. 3 private helpers. |
| Contracts define behavior | This document. Every API has input/output/raises spec.         |
| Systems fail at boundaries | HTTP boundary fully specified (timeout, status, size). File I/O failures caught and named. |
| Observable / debuggable | Metadata includes source, method, timestamp, char_count. OCR trigger prints notification. Error messages name the specific source. |
| Validate all inputs    | Source string validated (non-empty, max length). URL status validated. PDF content validated (char threshold). Text content validated (non-empty). |
| Fail fast and clearly  | `SystemExit` with actionable message on every failure. No empty text ever returned. |
| Never swallow errors   | `requests` exceptions caught and re-raised as `SystemExit` with context. `pdfplumber` errors caught with file path. `pytesseract` missing-binary error caught with install instructions (C-11). |
| No hardcoded secrets   | No secrets involved in S-2. |
| Treat inputs as untrusted | URL response size capped at 10 MB. File paths validated. PDF content validated. |
