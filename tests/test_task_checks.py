"""Tests for the task_checks utility module."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.instruction_unit_tests.task_checks import (
    _cache_key,
    check_docx_contains_text,
    check_docx_exists,
    check_file_created,
    check_pptx_contains_text,
    check_pptx_exists,
    check_pptx_has_slide_count,
    check_python_file_created,
    check_task_with_llm,
    check_xlsx_exists,
    count_pptx_slides,
    extract_text_from_docx,
    extract_text_from_pptx,
    llm_check,
)


# -----------------------------------------------------------------------
# Helpers for creating Office files in tests
# -----------------------------------------------------------------------


def _make_minimal_pptx(path: Path, num_slides: int = 1, texts: list[str] | None = None):
    """Create a minimal .pptx with *num_slides* slides."""
    if texts is None:
        texts = [f"Slide {i+1} content" for i in range(num_slides)]
    with zipfile.ZipFile(path, "w") as zf:
        # [Content_Types].xml
        ct = '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        for i in range(num_slides):
            ct += f'<Override PartName="/ppt/slides/slide{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        ct += "</Types>"
        zf.writestr("[Content_Types].xml", ct)
        # Slide XMLs
        for i in range(num_slides):
            text = texts[i] if i < len(texts) else ""
            slide_xml = (
                '<?xml version="1.0"?>'
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
                ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                "<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r>"
                f"<a:t>{text}</a:t>"
                "</a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>"
                "</p:sld>"
            )
            zf.writestr(f"ppt/slides/slide{i+1}.xml", slide_xml)


def _make_minimal_docx(path: Path, text: str = "Hello world"):
    """Create a minimal .docx with given text."""
    with zipfile.ZipFile(path, "w") as zf:
        doc_xml = (
            '<?xml version="1.0"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r>"
            f"<w:t>{text}</w:t>"
            "</w:r></w:p></w:body></w:document>"
        )
        zf.writestr("word/document.xml", doc_xml)


# -----------------------------------------------------------------------
# Text extraction
# -----------------------------------------------------------------------


class TestExtractTextFromPptx:
    def test_extracts_text(self, tmp_path: Path):
        pptx = tmp_path / "test.pptx"
        _make_minimal_pptx(pptx, 2, ["First slide", "Second slide"])
        text = extract_text_from_pptx(pptx)
        assert "First slide" in text
        assert "Second slide" in text

    def test_missing_file(self, tmp_path: Path):
        assert extract_text_from_pptx(tmp_path / "nope.pptx") == ""

    def test_invalid_zip(self, tmp_path: Path):
        bad = tmp_path / "bad.pptx"
        bad.write_text("not a zip")
        assert extract_text_from_pptx(bad) == ""


class TestExtractTextFromDocx:
    def test_extracts_text(self, tmp_path: Path):
        docx = tmp_path / "test.docx"
        _make_minimal_docx(docx, "Important document")
        text = extract_text_from_docx(docx)
        assert "Important document" in text

    def test_missing_file(self, tmp_path: Path):
        assert extract_text_from_docx(tmp_path / "nope.docx") == ""


class TestCountPptxSlides:
    def test_counts_slides(self, tmp_path: Path):
        pptx = tmp_path / "test.pptx"
        _make_minimal_pptx(pptx, 5)
        assert count_pptx_slides(pptx) == 5

    def test_missing_file(self, tmp_path: Path):
        assert count_pptx_slides(tmp_path / "nope.pptx") == 0


# -----------------------------------------------------------------------
# Deterministic skill checks
# -----------------------------------------------------------------------


class TestCheckPptxExists:
    def test_found_by_name(self, tmp_path: Path):
        _make_minimal_pptx(tmp_path / "report.pptx")
        ok, _ = check_pptx_exists(tmp_path, "report.pptx")
        assert ok

    def test_not_found(self, tmp_path: Path):
        ok, _ = check_pptx_exists(tmp_path, "report.pptx")
        assert not ok

    def test_any_pptx(self, tmp_path: Path):
        _make_minimal_pptx(tmp_path / "something.pptx")
        ok, _ = check_pptx_exists(tmp_path)
        assert ok

    def test_ignores_skill_dirs(self, tmp_path: Path):
        skill_dir = tmp_path / ".claude" / "skills"
        skill_dir.mkdir(parents=True)
        _make_minimal_pptx(skill_dir / "test.pptx")
        ok, _ = check_pptx_exists(tmp_path)
        assert not ok


class TestCheckDocxExists:
    def test_found(self, tmp_path: Path):
        _make_minimal_docx(tmp_path / "doc.docx")
        ok, _ = check_docx_exists(tmp_path, "doc.docx")
        assert ok

    def test_not_found(self, tmp_path: Path):
        ok, _ = check_docx_exists(tmp_path)
        assert not ok


class TestCheckXlsxExists:
    def test_found(self, tmp_path: Path):
        (tmp_path / "data.xlsx").write_bytes(b"fake xlsx")
        ok, _ = check_xlsx_exists(tmp_path, "data.xlsx")
        assert ok

    def test_not_found(self, tmp_path: Path):
        ok, _ = check_xlsx_exists(tmp_path)
        assert not ok


class TestCheckFileCreated:
    def test_glob_match(self, tmp_path: Path):
        (tmp_path / "output.csv").write_text("data")
        ok, _ = check_file_created(tmp_path, "*.csv")
        assert ok

    def test_no_match(self, tmp_path: Path):
        ok, _ = check_file_created(tmp_path, "*.csv")
        assert not ok

    def test_ignores_skill_dirs(self, tmp_path: Path):
        skill_dir = tmp_path / ".codex" / "skills"
        skill_dir.mkdir(parents=True)
        (skill_dir / "output.csv").write_text("data")
        ok, _ = check_file_created(tmp_path, "*.csv")
        assert not ok


class TestCheckPythonFileCreated:
    def test_found(self, tmp_path: Path):
        (tmp_path / "train.py").write_text("import torch")
        ok, _ = check_python_file_created(tmp_path)
        assert ok

    def test_ignores_skill_dirs(self, tmp_path: Path):
        skill_dir = tmp_path / ".claude" / "skills" / "ml"
        skill_dir.mkdir(parents=True)
        (skill_dir / "train.py").write_text("import torch")
        ok, _ = check_python_file_created(tmp_path)
        assert not ok


class TestCheckPptxHasSlideCount:
    def test_enough_slides(self, tmp_path: Path):
        _make_minimal_pptx(tmp_path / "report.pptx", 6)
        ok, _ = check_pptx_has_slide_count(tmp_path, "report.pptx", min_slides=6)
        assert ok

    def test_not_enough_slides(self, tmp_path: Path):
        _make_minimal_pptx(tmp_path / "report.pptx", 3)
        ok, _ = check_pptx_has_slide_count(tmp_path, "report.pptx", min_slides=6)
        assert not ok


class TestCheckPptxContainsText:
    def test_text_found(self, tmp_path: Path):
        _make_minimal_pptx(tmp_path / "report.pptx", 1, ["Thank you for your attention!"])
        ok, _ = check_pptx_contains_text(tmp_path, "report.pptx", "thank you")
        assert ok

    def test_text_not_found(self, tmp_path: Path):
        _make_minimal_pptx(tmp_path / "report.pptx", 1, ["Slide content"])
        ok, _ = check_pptx_contains_text(tmp_path, "report.pptx", "thank you")
        assert not ok


class TestCheckDocxContainsText:
    def test_text_found(self, tmp_path: Path):
        _make_minimal_docx(tmp_path / "doc.docx", "Q4 Financial Report")
        ok, _ = check_docx_contains_text(tmp_path, "doc.docx", "financial report")
        assert ok

    def test_text_not_found(self, tmp_path: Path):
        _make_minimal_docx(tmp_path / "doc.docx", "Other content")
        ok, _ = check_docx_contains_text(tmp_path, "doc.docx", "financial report")
        assert not ok


# -----------------------------------------------------------------------
# LLM check
# -----------------------------------------------------------------------


class TestLlmCheck:
    def test_no_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert llm_check("Is the sky blue?", "The sky is blue.") is None

    def test_caching(self, tmp_path: Path, monkeypatch):
        """Verify that cached results are returned without calling the API."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        # Pre-populate cache
        import data.instruction_unit_tests.task_checks as tc
        original_cache_dir = tc._LLM_CACHE_DIR
        tc._LLM_CACHE_DIR = tmp_path

        question = "Did the task succeed?"
        context = "The file was created."
        key = _cache_key(question, context)
        cache_file = tmp_path / f"{key}.json"
        cache_file.write_text(
            json.dumps({"result": True, "explanation": "cached answer"})
        )

        result = llm_check(question, context)
        assert result == (True, "cached answer")

        # Restore
        tc._LLM_CACHE_DIR = original_cache_dir

    def test_import_error_returns_none(self, monkeypatch):
        """If openai package is not installed, returns None."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        # Clear cache to force API call
        import data.instruction_unit_tests.task_checks as tc
        original_cache_dir = tc._LLM_CACHE_DIR
        tc._LLM_CACHE_DIR = Path("/tmp/nonexistent_cache_dir_test")

        with patch.dict("sys.modules", {"openai": None}):
            result = llm_check("test?", "context")
            assert result is None

        tc._LLM_CACHE_DIR = original_cache_dir


class TestCheckTaskWithLlm:
    def test_fallback_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        ok, reason = check_task_with_llm(
            Path("."),
            "Create a report",
            "Report content here",
            fallback=(True, "file exists"),
        )
        assert ok
        assert "file exists" in reason

    def test_default_fallback(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        ok, reason = check_task_with_llm(
            Path("."),
            "Create a report",
            "Report content here",
        )
        assert ok
        assert "LLM unavailable" in reason


class TestCacheKey:
    def test_deterministic(self):
        k1 = _cache_key("q1", "c1")
        k2 = _cache_key("q1", "c1")
        assert k1 == k2

    def test_different_inputs(self):
        k1 = _cache_key("q1", "c1")
        k2 = _cache_key("q2", "c1")
        assert k1 != k2
