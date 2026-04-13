"""S-2 Source Extraction tests. Contract: contracts/s-2-source-extraction.contract.md"""

import re
import stat
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest
import requests

from src.core.extract import extract_source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exit_msg(exc_info) -> str:
    """Extract the error message from a SystemExit."""
    return str(exc_info.value.code) if exc_info.value.code is not None else ""


def _mock_response(status_code=200, text="", content_length=None, headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.content = text.encode("utf-8") if isinstance(text, str) else text
    h = headers or {}
    if content_length is not None:
        h["Content-Length"] = str(content_length)
    resp.headers = h
    return resp


_ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


# ===========================================================================
# URL EXTRACTION — Happy Path
# ===========================================================================

class TestUrlHappy:
    # T-2.01
    def test_extract_text_from_valid_html(self):
        html = "<html><body><p>Hello world</p></body></html>"
        resp = _mock_response(text=html, content_length=len(html))
        with patch("src.core.extract.requests.get", return_value=resp):
            text, meta = extract_source("http://example.com")
        assert text == "Hello world"
        assert meta["method"] == "url"
        assert meta["char_count"] == 11

    # T-2.02
    def test_script_and_style_tags_stripped(self):
        html = (
            "<html><body>"
            "<script>var x = 1;</script>"
            "<style>.cls { color: red; }</style>"
            "<p>Content</p>"
            "</body></html>"
        )
        resp = _mock_response(text=html, content_length=len(html))
        with patch("src.core.extract.requests.get", return_value=resp):
            text, meta = extract_source("http://example.com")
        assert "Content" in text
        assert "var x" not in text
        assert "color" not in text

    # T-2.03
    def test_nav_footer_header_stripped(self):
        html = (
            "<html><body>"
            "<nav>NavStuff</nav>"
            "<header>HeaderStuff</header>"
            "<main>Text</main>"
            "<footer>FooterStuff</footer>"
            "</body></html>"
        )
        resp = _mock_response(text=html, content_length=len(html))
        with patch("src.core.extract.requests.get", return_value=resp):
            text, meta = extract_source("http://example.com")
        assert "Text" in text
        assert "NavStuff" not in text
        assert "HeaderStuff" not in text
        assert "FooterStuff" not in text

    # T-2.04
    def test_metadata_fields_populated(self):
        html = "<html><body><p>Some content</p></body></html>"
        resp = _mock_response(text=html, content_length=len(html))
        with patch("src.core.extract.requests.get", return_value=resp):
            text, meta = extract_source("http://example.com/page")
        assert meta["source"] == "http://example.com/page"
        assert meta["method"] == "url"
        assert _ISO8601_RE.match(meta["timestamp"])
        assert meta["char_count"] > 0
        assert meta["char_count"] == len(text)


# ===========================================================================
# URL EXTRACTION — Edge Cases
# ===========================================================================

class TestUrlEdge:
    # T-2.05
    def test_html_with_no_body_tag(self):
        html = "<html>Plain text only</html>"
        resp = _mock_response(text=html, content_length=len(html))
        with patch("src.core.extract.requests.get", return_value=resp):
            text, meta = extract_source("http://example.com")
        assert "Plain text only" in text

    # T-2.06
    def test_whitespace_collapsing(self):
        html = "<p>  lots   of    spaces  </p>"
        resp = _mock_response(text=html, content_length=len(html))
        with patch("src.core.extract.requests.get", return_value=resp):
            text, meta = extract_source("http://example.com")
        assert "  " not in text
        assert "lots of spaces" in text

    # T-2.07
    def test_response_exactly_at_10mb_limit(self):
        html = "<html><body><p>OK</p></body></html>"
        resp = _mock_response(text=html, content_length=10_485_760)
        with patch("src.core.extract.requests.get", return_value=resp):
            text, meta = extract_source("http://example.com")
        assert "OK" in text


# ===========================================================================
# URL EXTRACTION — Failure Cases
# ===========================================================================

class TestUrlFailure:
    # T-2.08
    def test_url_unreachable_connection_error(self):
        with patch("src.core.extract.requests.get", side_effect=requests.ConnectionError):
            with pytest.raises(SystemExit) as exc_info:
                extract_source("http://unreachable.example.com")
        msg = _exit_msg(exc_info)
        assert "unreachable.example.com" in msg
        assert "Cannot connect" in msg

    # T-2.09
    def test_url_timeout(self):
        with patch("src.core.extract.requests.get", side_effect=requests.Timeout):
            with pytest.raises(SystemExit) as exc_info:
                extract_source("http://slow.example.com")
        msg = _exit_msg(exc_info)
        assert "slow.example.com" in msg
        assert "timed out" in msg

    # T-2.10
    def test_url_returns_404(self):
        resp = _mock_response(status_code=404, text="Not Found")
        with patch("src.core.extract.requests.get", return_value=resp):
            with pytest.raises(SystemExit) as exc_info:
                extract_source("http://example.com/missing")
        msg = _exit_msg(exc_info)
        assert "HTTP 404" in msg
        assert "example.com/missing" in msg

    # T-2.11
    def test_url_returns_500(self):
        resp = _mock_response(status_code=500, text="Server Error")
        with patch("src.core.extract.requests.get", return_value=resp):
            with pytest.raises(SystemExit) as exc_info:
                extract_source("http://example.com/error")
        msg = _exit_msg(exc_info)
        assert "HTTP 500" in msg
        assert "example.com/error" in msg

    # T-2.12
    def test_url_response_exceeds_10mb(self):
        resp = _mock_response(text="x", content_length=20_000_000)
        with patch("src.core.extract.requests.get", return_value=resp):
            with pytest.raises(SystemExit) as exc_info:
                extract_source("http://example.com/huge")
        msg = _exit_msg(exc_info)
        assert "too large" in msg.lower()
        assert "example.com/huge" in msg

    # T-2.13
    def test_url_returns_empty_page(self):
        html = "<html><body></body></html>"
        resp = _mock_response(text=html, content_length=len(html))
        with patch("src.core.extract.requests.get", return_value=resp):
            with pytest.raises(SystemExit) as exc_info:
                extract_source("http://example.com/empty")
        msg = _exit_msg(exc_info)
        assert "no text" in msg.lower()
        assert "example.com/empty" in msg


# ===========================================================================
# PDF EXTRACTION — Happy Path
# ===========================================================================

class TestPdfHappy:
    # T-2.14
    def test_extract_text_from_text_native_pdf(self, tmp_path):
        pdf_path = tmp_path / "doc.pdf"
        pdf_path.write_bytes(b"fake pdf")
        page = MagicMock()
        page.extract_text.return_value = "A" * 500
        mock_pdf = MagicMock()
        mock_pdf.pages = [page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        with patch("src.core.extract.pdfplumber.open", return_value=mock_pdf):
            text, meta = extract_source(str(pdf_path))
        assert "A" * 500 in text
        assert meta["method"] == "pdf_text"

    # T-2.15
    def test_ocr_triggered_on_scanned_pdf(self, tmp_path):
        pdf_path = tmp_path / "scan.pdf"
        pdf_path.write_bytes(b"fake pdf")
        page = MagicMock()
        page.extract_text.return_value = ""
        page.to_image.return_value.original = MagicMock()
        mock_pdf = MagicMock()
        mock_pdf.pages = [page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        with patch("src.core.extract.pdfplumber.open", return_value=mock_pdf):
            with patch("src.core.extract.pytesseract.image_to_string", return_value="OCR text"):
                text, meta = extract_source(str(pdf_path))
        assert text == "OCR text"
        assert meta["method"] == "pdf_ocr"

    # T-2.16
    def test_ocr_notification_printed(self, tmp_path, capsys):
        pdf_path = tmp_path / "scan2.pdf"
        pdf_path.write_bytes(b"fake pdf")
        page = MagicMock()
        page.extract_text.return_value = ""
        page.to_image.return_value.original = MagicMock()
        mock_pdf = MagicMock()
        mock_pdf.pages = [page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        with patch("src.core.extract.pdfplumber.open", return_value=mock_pdf):
            with patch("src.core.extract.pytesseract.image_to_string", return_value="OCR text"):
                extract_source(str(pdf_path))
        captured = capsys.readouterr()
        assert "Scanned PDF detected" in captured.out

    # T-2.17
    def test_multi_page_pdf_concatenation(self, tmp_path):
        pdf_path = tmp_path / "multi.pdf"
        pdf_path.write_bytes(b"fake pdf")
        pages = []
        for i in range(3):
            p = MagicMock()
            p.extract_text.return_value = f"Page {i+1} content " + "x" * 50
            pages.append(p)
        mock_pdf = MagicMock()
        mock_pdf.pages = pages
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        with patch("src.core.extract.pdfplumber.open", return_value=mock_pdf):
            text, meta = extract_source(str(pdf_path))
        assert "Page 1 content" in text
        assert "Page 2 content" in text
        assert "Page 3 content" in text


# ===========================================================================
# PDF EXTRACTION — Edge Cases
# ===========================================================================

class TestPdfEdge:
    # T-2.18
    def test_pdf_exactly_50_chars_no_ocr(self, tmp_path):
        pdf_path = tmp_path / "border.pdf"
        pdf_path.write_bytes(b"fake pdf")
        page = MagicMock()
        page.extract_text.return_value = "A" * 50
        mock_pdf = MagicMock()
        mock_pdf.pages = [page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        with patch("src.core.extract.pdfplumber.open", return_value=mock_pdf):
            text, meta = extract_source(str(pdf_path))
        assert meta["method"] == "pdf_text"

    # T-2.19
    def test_pdf_49_chars_triggers_ocr(self, tmp_path):
        pdf_path = tmp_path / "border2.pdf"
        pdf_path.write_bytes(b"fake pdf")
        page = MagicMock()
        page.extract_text.return_value = "A" * 49
        page.to_image.return_value.original = MagicMock()
        mock_pdf = MagicMock()
        mock_pdf.pages = [page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        with patch("src.core.extract.pdfplumber.open", return_value=mock_pdf):
            with patch("src.core.extract.pytesseract.image_to_string", return_value="OCR result"):
                text, meta = extract_source(str(pdf_path))
        assert meta["method"] == "pdf_ocr"

    # T-2.20
    def test_pdf_path_with_spaces(self, tmp_path):
        pdf_dir = tmp_path / "my docs"
        pdf_dir.mkdir()
        pdf_path = pdf_dir / "my file.pdf"
        pdf_path.write_bytes(b"fake pdf")
        page = MagicMock()
        page.extract_text.return_value = "A" * 100
        mock_pdf = MagicMock()
        mock_pdf.pages = [page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        with patch("src.core.extract.pdfplumber.open", return_value=mock_pdf):
            text, meta = extract_source(str(pdf_path))
        assert meta["method"] == "pdf_text"


# ===========================================================================
# PDF EXTRACTION — Failure Cases
# ===========================================================================

class TestPdfFailure:
    # T-2.21
    def test_pdf_file_not_found(self):
        with pytest.raises(SystemExit) as exc_info:
            extract_source("/nonexistent/file.pdf")
        msg = _exit_msg(exc_info)
        assert "/nonexistent/file.pdf" in msg or "nonexistent" in msg
        assert "not found" in msg.lower()

    # T-2.22
    def test_corrupt_pdf(self, tmp_path):
        pdf_path = tmp_path / "corrupt.pdf"
        pdf_path.write_bytes(b"\x00\x01\x02\x03random garbage")
        with patch("src.core.extract.pdfplumber.open", side_effect=Exception("Invalid PDF")):
            with pytest.raises(SystemExit) as exc_info:
                extract_source(str(pdf_path))
        msg = _exit_msg(exc_info)
        assert "corrupt" in msg.lower() or str(pdf_path) in msg

    # T-2.23
    def test_tesseract_not_installed(self, tmp_path):
        pdf_path = tmp_path / "scan.pdf"
        pdf_path.write_bytes(b"fake pdf")
        page = MagicMock()
        page.extract_text.return_value = ""
        page.to_image.return_value.original = MagicMock()
        mock_pdf = MagicMock()
        mock_pdf.pages = [page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        class TesseractNotFoundError(Exception):
            pass

        with patch("src.core.extract.pdfplumber.open", return_value=mock_pdf):
            with patch("src.core.extract.pytesseract.image_to_string",
                       side_effect=TesseractNotFoundError("tesseract not found")):
                with patch("src.core.extract.pytesseract.pytesseract.TesseractNotFoundError",
                           TesseractNotFoundError, create=True):
                    with pytest.raises(SystemExit) as exc_info:
                        extract_source(str(pdf_path))
        msg = _exit_msg(exc_info)
        assert "Tesseract" in msg
        assert "C-11" in msg

    # T-2.24
    def test_pdf_and_ocr_both_empty(self, tmp_path):
        pdf_path = tmp_path / "empty.pdf"
        pdf_path.write_bytes(b"fake pdf")
        page = MagicMock()
        page.extract_text.return_value = ""
        page.to_image.return_value.original = MagicMock()
        mock_pdf = MagicMock()
        mock_pdf.pages = [page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        with patch("src.core.extract.pdfplumber.open", return_value=mock_pdf):
            with patch("src.core.extract.pytesseract.image_to_string", return_value=""):
                with pytest.raises(SystemExit) as exc_info:
                    extract_source(str(pdf_path))
        msg = _exit_msg(exc_info)
        assert "no text" in msg.lower()


# ===========================================================================
# TEXT / MARKDOWN EXTRACTION — Happy Path
# ===========================================================================

class TestTextHappy:
    # T-2.25
    def test_extract_text_from_txt_file(self, tmp_path):
        p = tmp_path / "hello.txt"
        p.write_text("Hello world", encoding="utf-8")
        text, meta = extract_source(str(p))
        assert text == "Hello world"
        assert meta["method"] == "text"

    # T-2.26
    def test_extract_text_from_md_file(self, tmp_path):
        p = tmp_path / "notes.md"
        content = "# Heading\n\nSome **bold** text."
        p.write_text(content, encoding="utf-8")
        text, meta = extract_source(str(p))
        assert text == content
        assert meta["method"] == "text"

    # T-2.27
    def test_text_metadata_fields_populated(self, tmp_path):
        p = tmp_path / "meta.txt"
        content = "Test content for metadata"
        p.write_text(content, encoding="utf-8")
        text, meta = extract_source(str(p))
        assert meta["source"] == str(p)
        assert _ISO8601_RE.match(meta["timestamp"])
        assert meta["char_count"] == len(content)


# ===========================================================================
# TEXT / MARKDOWN EXTRACTION — Edge Cases
# ===========================================================================

class TestTextEdge:
    # T-2.28
    def test_file_with_utf8_bom(self, tmp_path):
        p = tmp_path / "bom.txt"
        p.write_bytes(b"\xef\xbb\xbfBOM content")
        text, meta = extract_source(str(p))
        assert not text.startswith("\ufeff")
        assert "BOM content" in text

    # T-2.29
    def test_file_path_with_spaces(self, tmp_path):
        d = tmp_path / "my folder"
        d.mkdir()
        p = d / "my file.txt"
        p.write_text("Spaced path content", encoding="utf-8")
        text, meta = extract_source(str(p))
        assert text == "Spaced path content"

    # T-2.30
    def test_file_with_only_whitespace(self, tmp_path):
        p = tmp_path / "blank.txt"
        p.write_text("   \n\t  ", encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            extract_source(str(p))
        msg = _exit_msg(exc_info)
        assert "no text" in msg.lower()


# ===========================================================================
# TEXT / MARKDOWN EXTRACTION — Failure Cases
# ===========================================================================

class TestTextFailure:
    # T-2.31
    def test_text_file_not_found(self):
        with pytest.raises(SystemExit) as exc_info:
            extract_source("/nonexistent/file.txt")
        msg = _exit_msg(exc_info)
        assert "nonexistent" in msg
        assert "not found" in msg.lower()

    # T-2.32
    @pytest.mark.skipif(sys.platform == "win32", reason="chmod not reliable on Windows")
    def test_permission_error_on_text_file(self, tmp_path):
        p = tmp_path / "noperm.txt"
        p.write_text("content", encoding="utf-8")
        p.chmod(0o000)
        try:
            with pytest.raises(SystemExit) as exc_info:
                extract_source(str(p))
            msg = _exit_msg(exc_info)
            assert str(p) in msg or "noperm" in msg
        finally:
            p.chmod(stat.S_IRWXU)

    # T-2.33
    def test_non_utf8_encoded_file(self, tmp_path):
        p = tmp_path / "latin.txt"
        p.write_bytes(b"\xe9\xe8\xea")  # latin-1 accented chars, invalid utf-8
        with pytest.raises(SystemExit) as exc_info:
            extract_source(str(p))
        msg = _exit_msg(exc_info)
        assert str(p) in msg or "latin" in msg
        assert "encoding" in msg.lower()


# ===========================================================================
# DISPATCH LOGIC — Happy Path
# ===========================================================================

class TestDispatchHappy:
    # T-2.34
    def test_url_detected_from_http_prefix(self):
        html = "<html><body><p>Dispatch test</p></body></html>"
        resp = _mock_response(text=html, content_length=len(html))
        with patch("src.core.extract.requests.get", return_value=resp):
            text, meta = extract_source("http://example.com")
        assert meta["method"] == "url"

    # T-2.35
    def test_url_detected_from_https_prefix(self):
        html = "<html><body><p>Secure dispatch</p></body></html>"
        resp = _mock_response(text=html, content_length=len(html))
        with patch("src.core.extract.requests.get", return_value=resp):
            text, meta = extract_source("https://example.com")
        assert meta["method"] == "url"

    # T-2.36
    def test_pdf_detected_from_extension(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"fake pdf")
        page = MagicMock()
        page.extract_text.return_value = "A" * 100
        mock_pdf = MagicMock()
        mock_pdf.pages = [page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        with patch("src.core.extract.pdfplumber.open", return_value=mock_pdf):
            text, meta = extract_source(str(pdf_path))
        assert meta["method"].startswith("pdf")

    # T-2.37
    def test_text_fallback_for_txt(self, tmp_path):
        p = tmp_path / "test.txt"
        p.write_text("Text fallback", encoding="utf-8")
        text, meta = extract_source(str(p))
        assert meta["method"] == "text"

    # T-2.38
    def test_text_fallback_for_md(self, tmp_path):
        p = tmp_path / "test.md"
        p.write_text("Markdown fallback", encoding="utf-8")
        text, meta = extract_source(str(p))
        assert meta["method"] == "text"

    # T-2.39
    def test_text_fallback_for_extensionless(self, tmp_path):
        p = tmp_path / "noext"
        p.write_text("No extension content", encoding="utf-8")
        text, meta = extract_source(str(p))
        assert meta["method"] == "text"


# ===========================================================================
# DISPATCH LOGIC — Edge Cases
# ===========================================================================

class TestDispatchEdge:
    # T-2.40
    def test_pdf_extension_case_insensitive(self, tmp_path):
        pdf_path = tmp_path / "test.PDF"
        pdf_path.write_bytes(b"fake pdf")
        page = MagicMock()
        page.extract_text.return_value = "A" * 100
        mock_pdf = MagicMock()
        mock_pdf.pages = [page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        with patch("src.core.extract.pdfplumber.open", return_value=mock_pdf):
            text, meta = extract_source(str(pdf_path))
        assert meta["method"].startswith("pdf")

    # T-2.41
    def test_url_with_pdf_in_path(self):
        html = "<html><body><p>URL with pdf extension</p></body></html>"
        resp = _mock_response(text=html, content_length=len(html))
        with patch("src.core.extract.requests.get", return_value=resp):
            text, meta = extract_source("https://example.com/doc.pdf")
        assert meta["method"] == "url"


# ===========================================================================
# DISPATCH LOGIC — Failure Cases
# ===========================================================================

class TestDispatchFailure:
    # T-2.42
    def test_empty_source_string(self):
        with pytest.raises(SystemExit) as exc_info:
            extract_source("")
        msg = _exit_msg(exc_info)
        assert "non-empty" in msg.lower() or "empty" in msg.lower()

    # T-2.43
    def test_source_string_exceeds_2048_chars(self):
        with pytest.raises(SystemExit) as exc_info:
            extract_source("x" * 2049)
        msg = _exit_msg(exc_info)
        assert "too long" in msg.lower() or "2048" in msg
