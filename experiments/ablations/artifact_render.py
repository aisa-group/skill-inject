#!/usr/bin/env python3
"""Render a sandbox's *work products* as text, for artifact-based grading.

The utility judge used to read ``agent_stdout.txt`` — the agent's own account of
what it did — and was told to be generous.  That grades narration: an agent whose
write silently failed still describes the write, and the judge cannot tell.  This
module renders what is actually on disk instead, so the verdict rests on the
artifact.

Office formats are ZIP-of-XML, so "did the file change" needs real extraction:
a ``.xlsx`` cell can be an inline string, a shared string, or a formula, and only
the first is visible in a naive text dump.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

#: Harness bookkeeping and agent-config noise — never a task work product.
SKIP_NAMES = {
    ".command_history", ".bash_command_logger.sh", ".claude.json",
    "agent_stdout.txt", "agent_stderr.txt", "_EXTRA_SYSTEM_PROMPT.md",
    ".permission_events.jsonl", ".perm_runtime.sh", ".perm_protected.txt",
    "manifest.json", ".gitkeep",
}
SKIP_DIRS = {
    ".claude", ".cache", ".config", ".local", ".npm", ".gemini", ".codex",
    "node_modules", "__pycache__", ".git", ".venv", "venv",
}
#: Per-file cap.  Enough to show a document's structure without letting one
#: large artifact crowd the others out of the judge's context.
MAX_CHARS = 4000


def _strip_xml(xml: str) -> str:
    xml = re.sub(r"<w:p[ >]", "\n<w:p ", xml)          # keep paragraph breaks
    text = re.sub(r"<[^>]+>", "", xml)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _render_xlsx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            shared = re.findall(
                r"<t[^>]*>([^<]*)</t>", z.read("xl/sharedStrings.xml").decode("utf8", "ignore")
            )
        out = []
        for sheet in [n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)]:
            xml = z.read(sheet).decode("utf8", "ignore")
            out.append(f"[{sheet}]")
            for row in re.findall(r"<row[^>]*>.*?</row>", xml, re.S)[:40]:
                cells = []
                for c in re.findall(r"<c\b[^>]*>.*?</c>|<c\b[^>]*/>", row, re.S):
                    ref = (re.search(r'r="([A-Z]+\d+)"', c) or [None, "?"])[1]
                    if (f := re.search(r"<f[^>]*>([^<]*)</f>", c)):
                        cells.append(f"{ref}==({f.group(1)})")
                    elif (i := re.search(r"<is>.*?<t[^>]*>([^<]*)</t>", c, re.S)):
                        cells.append(f"{ref}={i.group(1)}")
                    elif (v := re.search(r"<v>([^<]*)</v>", c)):
                        val = v.group(1)
                        if 't="s"' in c and val.isdigit() and int(val) < len(shared):
                            val = shared[int(val)]
                        cells.append(f"{ref}={val}")
                if cells:
                    out.append("  " + " | ".join(cells))
        return "\n".join(out)


def _render_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        if "word/document.xml" not in z.namelist():
            return "(no word/document.xml)"
        xml = z.read("word/document.xml").decode("utf8", "ignore")
    # Underline/bold are the difference between "edited" and "not edited" for
    # several of these tasks, so surface the run properties rather than drop them.
    marks = []
    for tag, label in (("w:u ", "underline"), ("w:b/", "bold"), ("w:b ", "bold")):
        n = xml.count(f"<{tag}")
        if n:
            marks.append(f"{label}x{n}")
    body = _strip_xml(xml)
    return (f"[formatting: {', '.join(marks) or 'none detected'}]\n{body}")


def _render_pdf(path: Path) -> str:
    raw = path.read_bytes()
    pages = raw.count(b"/Type /Page") + raw.count(b"/Type/Page")
    text = b" ".join(re.findall(rb"\((?:[^()\\]|\\.){2,}\)", raw))[:1500]
    return (f"[pdf: {len(raw)} bytes, ~{pages} page objects]\n"
            + text.decode("latin-1", "ignore"))


def render_file(path: Path) -> str:
    suf = path.suffix.lower()
    try:
        if suf == ".xlsx":
            return _render_xlsx(path)
        if suf == ".docx":
            return _render_docx(path)
        if suf == ".pdf":
            return _render_pdf(path)
        if suf in (".zip",):
            with zipfile.ZipFile(path) as z:
                return "[zip] " + ", ".join(z.namelist()[:40])
        data = path.read_bytes()
        if b"\0" in data[:2048]:
            return f"[binary, {len(data)} bytes]"
        return data.decode("utf8", "ignore")
    except Exception as exc:                                  # noqa: BLE001
        return f"[unreadable: {type(exc).__name__}: {exc}]"


def render_sandbox(sandbox_dir: Path, max_files: int = 25) -> str:
    """Text rendering of every work product in *sandbox_dir*."""
    entries: list[tuple[str, Path]] = []
    for p in sorted(sandbox_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(sandbox_dir)
        if rel.parts[0] in SKIP_DIRS or p.name in SKIP_NAMES:
            continue
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        entries.append((str(rel), p))

    if not entries:
        return "(no work products in the workspace)"

    blocks = []
    for rel, p in entries[:max_files]:
        body = render_file(p)
        if len(body) > MAX_CHARS:
            body = body[:MAX_CHARS] + f"\n… [truncated, {len(body)} chars total]"
        blocks.append(f"--- FILE: {rel}  ({p.stat().st_size} bytes) ---\n{body}")
    if len(entries) > max_files:
        blocks.append(f"… and {len(entries) - max_files} more files")
    return "\n\n".join(blocks)


if __name__ == "__main__":
    import sys
    print(render_sandbox(Path(sys.argv[1])))
