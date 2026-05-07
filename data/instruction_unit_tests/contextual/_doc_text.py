"""Extract plain text from Office docs (.docx, .pptx, .xlsx) using stdlib only.

Office formats are zip archives of XML. We pull all text-bearing elements
(<w:t> for docx, <a:t> for pptx, <t> in xl/sharedStrings.xml for xlsx) and
return their concatenation. This is good enough for substring/regex checks
on document content — not a faithful reconstruction.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

_W_T = re.compile(r"<w:t[^>]*>([^<]*)</w:t>", re.DOTALL)
_A_T = re.compile(r"<a:t[^>]*>([^<]*)</a:t>", re.DOTALL)
_X_T = re.compile(r"<t[^>]*>([^<]*)</t>", re.DOTALL)


def _read_zip_member(zf: zipfile.ZipFile, name: str) -> str:
    try:
        return zf.read(name).decode("utf-8", errors="ignore")
    except KeyError:
        return ""


def extract_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            xml = _read_zip_member(zf, "word/document.xml")
    except (zipfile.BadZipFile, OSError):
        return ""
    return " ".join(_W_T.findall(xml))


def extract_pptx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            slide_names = sorted(
                n for n in zf.namelist()
                if n.startswith("ppt/slides/slide") and n.endswith(".xml")
            )
            chunks = [_read_zip_member(zf, n) for n in slide_names]
    except (zipfile.BadZipFile, OSError):
        return ""
    return " ".join(t for chunk in chunks for t in _A_T.findall(chunk))


def extract_xlsx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            shared = _read_zip_member(zf, "xl/sharedStrings.xml")
            sheet_names = sorted(
                n for n in zf.namelist()
                if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
            )
            sheet_chunks = [_read_zip_member(zf, n) for n in sheet_names]
    except (zipfile.BadZipFile, OSError):
        return ""
    parts = _X_T.findall(shared) if shared else []
    for chunk in sheet_chunks:
        parts.extend(_X_T.findall(chunk))
    return " ".join(parts)


def extract_doc_text(path: Path) -> str:
    suf = path.suffix.lower()
    if suf == ".docx":
        return extract_docx_text(path)
    if suf == ".pptx":
        return extract_pptx_text(path)
    if suf == ".xlsx":
        return extract_xlsx_text(path)
    return ""


def all_doc_text(sandbox_dir: Path) -> dict[Path, str]:
    """Return {path: extracted_text} for every Office doc under sandbox_dir."""
    out: dict[Path, str] = {}
    for ext in ("*.docx", "*.pptx", "*.xlsx"):
        for f in sandbox_dir.rglob(ext):
            if any(skip in str(f) for skip in (".claude", ".codex", ".gemini", "__pycache__")):
                continue
            text = extract_doc_text(f)
            if text:
                out[f] = text
    return out


def any_doc_matches(sandbox_dir: Path, pattern: str) -> Path | None:
    """Return path of first Office doc whose text matches *pattern* (case-insensitive)."""
    rx = re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for f, text in all_doc_text(sandbox_dir).items():
        if rx.search(text):
            return f
    return None
