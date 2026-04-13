"""Source extraction: URL, PDF, and text files. Contract: contracts/s-2-source-extraction.contract.md"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
import pytesseract
import requests
from bs4 import BeautifulSoup

_CONNECT_TIMEOUT = 10
_READ_TIMEOUT = 30
_MAX_RESPONSE_SIZE = 10_485_760
_MIN_PDF_CHARS = 50
_STRIPPED_TAGS = ["script", "style", "nav", "footer", "header"]
_MAX_SOURCE_LEN = 2048


def _fail(msg: str) -> None:
    sys.exit(msg)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _meta(source: str, method: str, text: str) -> dict:
    return {
        "source": source,
        "method": method,
        "timestamp": _timestamp(),
        "char_count": len(text),
    }


def extract_source(source: str) -> tuple[str, dict]:
    if not source:
        _fail("Source must be non-empty.")
    if len(source) > _MAX_SOURCE_LEN:
        _fail(f"Source string too long ({len(source)} chars). Maximum is {_MAX_SOURCE_LEN}.")

    if source.startswith("http://") or source.startswith("https://"):
        text, metadata = _extract_url(source)
    elif source.lower().endswith(".pdf"):
        text, metadata = _extract_pdf(source)
    else:
        text, metadata = _extract_text(source)

    if not text.strip():
        _fail(f"Extraction produced no text from '{source}'.")

    return text, metadata


def _extract_url(url: str) -> tuple[str, dict]:
    try:
        resp = requests.get(
            url,
            timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
            headers={"User-Agent": "llm-wiki/0.1"},
        )
    except requests.ConnectionError:
        _fail(f"Cannot connect to URL: '{url}'.")
    except requests.Timeout:
        _fail(f"URL request timed out: '{url}'.")
    except requests.RequestException as e:
        _fail(f"URL request failed: '{url}': {e}")

    content_length = resp.headers.get("Content-Length")
    if content_length and int(content_length) > _MAX_RESPONSE_SIZE:
        _fail(f"Response too large (>10 MB): '{url}'.")

    if resp.status_code != 200:
        _fail(f"URL returned HTTP {resp.status_code}: '{url}'.")

    soup = BeautifulSoup(resp.text, "html.parser")

    for tag_name in _STRIPPED_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    raw_text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", raw_text).strip()

    return text, _meta(url, "url", text)


def _extract_pdf(path: str) -> tuple[str, dict]:
    p = Path(path)
    if not p.exists():
        _fail(f"PDF file not found: '{path}'.")

    try:
        with pdfplumber.open(path) as pdf:
            page_texts = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    page_texts.append(t)
            full_text = "\n".join(page_texts)
            pages_for_ocr = pdf.pages
    except Exception:
        _fail(f"Cannot read PDF file: '{path}'. File may be corrupt.")

    if len(full_text.strip()) >= _MIN_PDF_CHARS:
        return full_text, _meta(path, "pdf_text", full_text)

    print("Scanned PDF detected. Running OCR...")
    try:
        ocr_texts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                img = page.to_image().original
                t = pytesseract.image_to_string(img)
                if t:
                    ocr_texts.append(t)
        ocr_text = "\n".join(ocr_texts)
    except pytesseract.pytesseract.TesseractNotFoundError:
        _fail(
            "Tesseract is not installed. Install it from "
            "https://github.com/tesseract-ocr/tesseract "
            "and ensure it is on your PATH (C-11)."
        )
    except Exception:
        _fail(f"OCR failed on PDF: '{path}'.")

    return ocr_text, _meta(path, "pdf_ocr", ocr_text)


def _extract_text(path: str) -> tuple[str, dict]:
    p = Path(path)
    if not p.exists():
        _fail(f"File not found: '{path}'.")

    try:
        text = p.read_text(encoding="utf-8-sig")
    except PermissionError:
        _fail(f"Permission denied reading file: '{path}'.")
    except UnicodeDecodeError:
        _fail(f"File encoding error: '{path}'. Expected UTF-8 encoding.")

    return text, _meta(path, "text", text)
