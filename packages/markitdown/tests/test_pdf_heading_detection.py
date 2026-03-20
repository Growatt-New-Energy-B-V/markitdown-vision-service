#!/usr/bin/env python3 -m pytest
"""Tests for font-based heading detection in PDF conversion.

These tests exercise the heading detection logic in isolation (pure-Python,
no PDF file needed for most cases) and with the real sample-report.pdf fixture
for E2E verification.
"""

import os
import pytest

from markitdown.converters._pdf_converter import (
    _H1_RATIO,
    _H2_RATIO,
    _H3_RATIO,
    _MAX_HEADING_LINE_CHARS,
    _build_line,
    _classify_line_as_heading,
    _compute_body_font_size,
    _group_words_into_lines,
    _extract_text_with_headings,
)

TEST_FILES_DIR = os.path.join(os.path.dirname(__file__), "test_files")


# ---------------------------------------------------------------------------
# Helpers for constructing synthetic word dicts
# ---------------------------------------------------------------------------


def _make_word(text: str, size: float, top: float, x0: float = 50.0, fontname: str = "Helvetica") -> dict:
    """Create a synthetic pdfplumber word dict with font metadata."""
    return {
        "text": text,
        "size": size,
        "top": top,
        "x0": x0,
        "x1": x0 + len(text) * size * 0.6,  # rough width estimate
        "fontname": fontname,
    }


def _make_page_stub(words: list[dict], height: float = 792.0):
    """Create a minimal page stub that supports extract_words()."""

    class _PageStub:
        def __init__(self, words, height):
            self._words = words
            self.height = height

        def extract_words(self, extra_attrs=None, **kwargs):
            return self._words

        def extract_text(self):
            return " ".join(w["text"] for w in self._words)

    return _PageStub(words, height)


# ---------------------------------------------------------------------------
# _compute_body_font_size
# ---------------------------------------------------------------------------


class TestComputeBodyFontSize:
    """The mode of font sizes on a page identifies the body font."""

    def test_mode_with_majority_font(self):
        """Mode of [10, 10, 18, 10, 13, 10] should be 10."""
        words = [
            _make_word("a", 10, 100),
            _make_word("b", 10, 110),
            _make_word("c", 18, 50),
            _make_word("d", 10, 120),
            _make_word("e", 13, 60),
            _make_word("f", 10, 130),
        ]
        result = _compute_body_font_size(words)
        assert result == 10.0

    def test_single_font_size(self):
        """A document with one font size returns that size."""
        words = [_make_word("hello", 12, 100), _make_word("world", 12, 100)]
        result = _compute_body_font_size(words)
        assert result == 12.0

    def test_no_size_metadata(self):
        """Words without 'size' key return None."""
        words = [{"text": "hello", "top": 100, "x0": 50}]
        result = _compute_body_font_size(words)
        assert result is None

    def test_empty_words(self):
        """Empty word list returns None."""
        result = _compute_body_font_size([])
        assert result is None

    def test_sizes_rounded_to_half_point(self):
        """Sizes like 9.9 and 10.1 should both round to 10.0 and be grouped."""
        words = [
            _make_word("a", 9.9, 100),
            _make_word("b", 10.1, 110),
            _make_word("c", 18.0, 50),
        ]
        # Both 9.9→10.0 and 10.1→10.0 — mode should be 10.0
        result = _compute_body_font_size(words)
        assert result == 10.0

    def test_threshold_verification(self):
        """Verify H1/H2/H3 thresholds work correctly for body=10."""
        words = [_make_word("x", 10, y) for y in range(0, 400, 10)]
        body = _compute_body_font_size(words)
        assert body == 10.0
        assert 18.0 >= body * _H1_RATIO  # 18 >= 18 ✓
        assert 13.0 >= body * _H2_RATIO  # 13 >= 13 ✓
        assert 11.0 >= body * _H3_RATIO  # 11 >= 11 ✓


# ---------------------------------------------------------------------------
# _classify_line_as_heading
# ---------------------------------------------------------------------------


class TestClassifyLineAsHeading:
    """Line classification based on font size thresholds."""

    PAGE_HEIGHT = 792.0
    BODY_SIZE = 10.0

    def _make_line(self, text: str, size: float, top: float = 400.0, fontname: str = "Helvetica") -> dict:
        words = [_make_word(w, size, top, fontname=fontname) for w in text.split()]
        return _build_line(words, self.PAGE_HEIGHT)

    # --- H1 ---

    def test_h1_detected_at_1_8x_body(self):
        """A line at 1.8x body size should be H1."""
        line = self._make_line("Executive Summary", self.BODY_SIZE * 1.8)
        assert _classify_line_as_heading(line, self.BODY_SIZE) == "#"

    def test_h1_detected_above_1_8x_body(self):
        """A line well above 1.8x body size should still be H1."""
        line = self._make_line("Title", self.BODY_SIZE * 2.5)
        assert _classify_line_as_heading(line, self.BODY_SIZE) == "#"

    # --- H2 ---

    def test_h2_detected_at_1_3x_body(self):
        """A line at 1.3x body size should be H2."""
        line = self._make_line("Introduction", self.BODY_SIZE * 1.3)
        assert _classify_line_as_heading(line, self.BODY_SIZE) == "##"

    def test_h2_not_h1_below_1_8x(self):
        """A line at 1.5x should be H2, not H1."""
        line = self._make_line("Section", self.BODY_SIZE * 1.5)
        assert _classify_line_as_heading(line, self.BODY_SIZE) == "##"

    # --- H3 (requires bold) ---

    def test_h3_bold_font_at_1_1x(self):
        """A bold line at 1.1x body size should be H3."""
        line = self._make_line("Subsection", self.BODY_SIZE * 1.15, fontname="Helvetica-Bold")
        assert _classify_line_as_heading(line, self.BODY_SIZE) == "###"

    def test_h3_requires_bold(self):
        """A non-bold line at 1.1x should NOT be classified as heading."""
        line = self._make_line("Not A Heading", self.BODY_SIZE * 1.15, fontname="Helvetica")
        assert _classify_line_as_heading(line, self.BODY_SIZE) is None

    def test_heavy_font_counts_as_bold(self):
        """Fonts with 'Heavy' in the name should also trigger H3."""
        line = self._make_line("Key Point", self.BODY_SIZE * 1.15, fontname="Futura-Heavy")
        assert _classify_line_as_heading(line, self.BODY_SIZE) == "###"

    # --- Long line rejection ---

    def test_long_line_not_heading(self):
        """A line longer than 80 chars should not be classified as a heading."""
        long_text = "This is a very long line that exceeds eighty characters and should not be a heading"
        assert len(long_text) > _MAX_HEADING_LINE_CHARS
        line = self._make_line(long_text, self.BODY_SIZE * 1.8)  # even at H1 size
        assert _classify_line_as_heading(line, self.BODY_SIZE) is None

    def test_line_exactly_80_chars_is_allowed(self):
        """A line of exactly 80 chars should pass the length check."""
        text_80 = "A" * 80
        assert len(text_80) == _MAX_HEADING_LINE_CHARS
        line = self._make_line(text_80, self.BODY_SIZE * 1.8)
        assert _classify_line_as_heading(line, self.BODY_SIZE) == "#"

    # --- Header/footer rejection ---

    def test_header_line_not_classified(self):
        """Lines in the top 5% of the page should not be headings."""
        # top 5% of 792 = y < 39.6
        line = self._make_line("Page 1", self.BODY_SIZE * 2.0, top=20.0)
        assert _classify_line_as_heading(line, self.BODY_SIZE) is None

    def test_footer_line_not_classified(self):
        """Lines in the bottom 5% of the page should not be headings."""
        # bottom 5% of 792 = y > 752.4
        line = self._make_line("Confidential", self.BODY_SIZE * 2.0, top=760.0)
        assert _classify_line_as_heading(line, self.BODY_SIZE) is None

    # --- No headings with uniform font size ---

    def test_uniform_font_produces_no_headings(self):
        """When all words have the same font size, nothing qualifies as a heading."""
        body_size = 12.0
        lines_text = ["Section One", "Body paragraph text", "Another Section", "More body text"]
        for text in lines_text:
            line = self._make_line(text, body_size)
            assert _classify_line_as_heading(line, body_size) is None, (
                f"Expected no heading for '{text}' with uniform font size"
            )


# ---------------------------------------------------------------------------
# _extract_text_with_headings  (integration of full pipeline on synthetic data)
# ---------------------------------------------------------------------------


def _body_paragraph(body_size: float, start_y: float = 200.0, count: int = 8) -> list[dict]:
    """Return a list of body-size words to anchor the mode computation at body_size.

    Having more body words than heading words ensures the mode is body_size.
    """
    lorem = ["The", "quick", "brown", "fox", "jumps", "over", "the", "lazy"]
    return [_make_word(lorem[i % len(lorem)], body_size, start_y + i * 14.0, x0=50.0 + i * 40) for i in range(count)]


class TestExtractTextWithHeadings:
    """Full pipeline test using synthetic page stubs.

    Note: font-size mode computation requires the body words to outnumber the
    heading words.  All tests here build realistic word lists with a majority of
    body-size words so the mode correctly identifies the body font size.
    """

    PAGE_HEIGHT = 792.0

    def _run(self, words: list[dict]) -> str | None:
        page = _make_page_stub(words, self.PAGE_HEIGHT)
        return _extract_text_with_headings(page)

    def test_heading_prefix_added(self):
        """A large font line followed by body text gets a heading prefix."""
        body_size = 10.0
        heading_size = body_size * 1.5  # 15pt → H2 (≥ 13, < 18)
        words = (
            [_make_word("Introduction", heading_size, 100.0)]
            + _body_paragraph(body_size, start_y=140.0)
        )
        result = self._run(words)
        assert result is not None
        heading_lines = [l for l in result.splitlines() if l.startswith("#")]
        assert len(heading_lines) >= 1, f"No headings found in: {result!r}"
        assert any("Introduction" in l for l in heading_lines)

    def test_body_text_has_no_prefix(self):
        """Body-size lines should appear without heading prefix."""
        body_size = 10.0
        heading_size = body_size * 1.5
        words = (
            [_make_word("Title", heading_size, 50.0)]
            + _body_paragraph(body_size, start_y=120.0)
        )
        result = self._run(words)
        assert result is not None
        lines = result.splitlines()
        body_lines = [l for l in lines if not l.startswith("#")]
        assert len(body_lines) >= 1, f"No body lines found in: {result!r}"

    def test_no_words_returns_none(self):
        """Page with no extractable words should return None."""
        page = _make_page_stub([], self.PAGE_HEIGHT)
        result = _extract_text_with_headings(page)
        assert result is None

    def test_uniform_font_no_headings(self):
        """All same-size words produce output without any heading markers."""
        words = [
            _make_word("Section", 12.0, 100.0),
            _make_word("One", 12.0, 100.0),
            _make_word("Body", 12.0, 130.0),
            _make_word("text.", 12.0, 130.0),
            _make_word("More", 12.0, 150.0),
            _make_word("words", 12.0, 150.0),
        ]
        result = self._run(words)
        assert result is not None
        assert "#" not in result, f"Expected no headings in: {result!r}"

    def test_multi_line_heading_merged(self):
        """Two consecutive lines with the same large font are merged into one heading.

        The Y gap between the two heading lines is small (< _LINE_Y_TOLERANCE * 2)
        so they end up on the same logical line and get merged.
        """
        body_size = 10.0
        heading_size = body_size * 1.5  # H2
        # Y gap of 4 points — within the 2x tolerance so they group into one line
        words = (
            [
                _make_word("Comprehensive", heading_size, 100.0, x0=50.0),
                _make_word("Overview", heading_size, 103.0, x0=250.0),  # same line, 3pt gap
            ]
            + _body_paragraph(body_size, start_y=200.0)
        )
        result = self._run(words)
        assert result is not None
        heading_lines = [l for l in result.splitlines() if l.startswith("#")]
        assert len(heading_lines) == 1, f"Expected 1 merged heading, got: {heading_lines}"
        assert "Comprehensive" in heading_lines[0]
        assert "Overview" in heading_lines[0]

    def test_header_footer_region_filtered(self):
        """Words in top/bottom 5% of page height are excluded from output."""
        body_size = 10.0
        heading_size = body_size * 1.5
        words = (
            [_make_word("PageNum", body_size, 10.0)]  # top header (< 5% = 39.6)
            + [_make_word("Introduction", heading_size, 200.0)]
            + _body_paragraph(body_size, start_y=250.0)
            + [_make_word("Footer", body_size, 780.0)]  # bottom footer (> 95% = 752.4)
        )
        result = self._run(words)
        assert result is not None
        assert "PageNum" not in result, "Header word should be filtered"
        assert "Footer" not in result, "Footer word should be filtered"
        assert "Introduction" in result

    def test_h1_prefix(self):
        """Lines at ≥ 1.8x body size get # prefix."""
        body_size = 10.0
        heading_size = body_size * 2.0  # 20pt → H1 (≥ 18)
        words = (
            [
                _make_word("Major", heading_size, 100.0, x0=50.0),
                _make_word("Title", heading_size, 100.0, x0=160.0),
            ]
            + _body_paragraph(body_size, start_y=150.0)
        )
        result = self._run(words)
        assert result is not None
        h1_lines = [l for l in result.splitlines() if l.startswith("# ")]
        assert len(h1_lines) >= 1, f"Expected an H1 heading in: {result!r}"
        assert any("Major" in l for l in h1_lines)

    def test_h3_bold_only(self):
        """Bold font at 1.1x body size gets ### prefix."""
        body_size = 10.0
        heading_size = body_size * 1.15  # 11.5pt → H3 only if bold
        words = (
            [_make_word("Note", heading_size, 100.0, fontname="Arial-Bold")]
            + _body_paragraph(body_size, start_y=150.0)
        )
        result = self._run(words)
        assert result is not None
        h3_lines = [l for l in result.splitlines() if l.startswith("### ")]
        assert len(h3_lines) >= 1, f"Expected an H3 heading in: {result!r}"
        assert any("Note" in l for l in h3_lines)


# ---------------------------------------------------------------------------
# E2E test with sample-report.pdf
# ---------------------------------------------------------------------------


class TestSampleReportPdf:
    """End-to-end test using the real sample-report.pdf fixture."""

    PDF_PATH = os.path.join(TEST_FILES_DIR, "sample-report.pdf")

    @pytest.fixture(autouse=True)
    def require_pdf(self):
        if not os.path.exists(self.PDF_PATH):
            pytest.skip(f"sample-report.pdf not found at {self.PDF_PATH}")

    def test_output_contains_section_headings(self):
        """The converted PDF should contain markdown section headings."""
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(self.PDF_PATH)
        text = result.text_content

        # The document must contain at least some heading markers
        heading_lines = [l for l in text.splitlines() if l.startswith("#")]
        assert len(heading_lines) >= 1, (
            f"Expected at least 1 heading in output, but none found.\n"
            f"First 500 chars:\n{text[:500]}"
        )

    def test_body_text_not_prefixed(self):
        """Body text paragraphs should not get heading prefixes."""
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(self.PDF_PATH)
        text = result.text_content

        # Lines that are long (> 80 chars) should not have heading prefixes
        for line in text.splitlines():
            if line.startswith("#"):
                content = line.lstrip("# ").strip()
                assert len(content) <= _MAX_HEADING_LINE_CHARS, (
                    f"Heading line exceeds {_MAX_HEADING_LINE_CHARS} chars: {line!r}"
                )

    def test_output_is_nonempty(self):
        """The PDF should produce non-empty output."""
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(self.PDF_PATH)
        assert result.text_content.strip(), "Expected non-empty markdown output"
