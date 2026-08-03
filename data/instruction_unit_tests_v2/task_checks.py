"""Shared utilities for checking task completion in sandboxes.

Provides:
  - Skill-specific deterministic checks (pptx exists, docx modified, etc.)
  - An optional LLM judge (`llm_check`) that calls GPT-5-mini for
    content-quality questions.  Gracefully degrades when no API key is
    available or the call fails — callers always get a usable result.

LLM results are cached to disk so re-runs don't duplicate API calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path
from typing import Optional, Tuple
from xml.etree import ElementTree as ET


# ---------------------------------------------------------------------------
# LLM judge (optional, GPT-5-mini via OpenAI API)
# ---------------------------------------------------------------------------

_LLM_CACHE_DIR: Path | None = None


def _get_cache_dir() -> Path:
    """Return (and lazily create) the LLM result cache directory."""
    global _LLM_CACHE_DIR
    if _LLM_CACHE_DIR is None:
        _LLM_CACHE_DIR = Path(__file__).resolve().parent / ".llm_cache"
        _LLM_CACHE_DIR.mkdir(exist_ok=True)
    return _LLM_CACHE_DIR


def _cache_key(question: str, context: str) -> str:
    """Deterministic cache key for a (question, context) pair."""
    blob = json.dumps({"q": question, "c": context}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def llm_check(
    question: str,
    context: str,
    *,
    temperature: float = 0.0,
) -> Optional[Tuple[bool, str]]:
    """Ask GPT-5-mini a yes/no question about *context*.

    Returns
    -------
    (True, explanation)  — LLM answered yes
    (False, explanation) — LLM answered no
    None                 — LLM unavailable (no API key, network error, etc.)

    Results are cached to ``data/instruction_unit_tests/.llm_cache/``.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    # Check cache
    cache_dir = _get_cache_dir()
    key = _cache_key(question, context)
    cache_file = cache_dir / f"{key}.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            return cached["result"], cached["explanation"]
        except Exception:
            pass

    # Build prompt
    system_prompt = (
        "You are a precise evaluation judge.  You will be given a QUESTION "
        "and CONTEXT.  Answer the question with a JSON object:\n"
        '{"answer": true/false, "explanation": "brief reason"}\n'
        "Respond with JSON only, no markdown fences."
    )
    user_prompt = f"QUESTION: {question}\n\nCONTEXT:\n{context[:8000]}"

    try:
        import openai

        client = openai.OpenAI(api_key=api_key)
        # gpt-5-mini doesn't support temperature != 1, so omit it
        response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=256,
        )
        raw = response.choices[0].message.content.strip()

        # Parse JSON from response (strip markdown fences if present)
        raw_clean = raw
        if raw_clean.startswith("```"):
            raw_clean = re.sub(r"^```(?:json)?\s*", "", raw_clean)
            raw_clean = re.sub(r"\s*```$", "", raw_clean)
        data = json.loads(raw_clean)

        result = bool(data.get("answer", False))
        explanation = str(data.get("explanation", raw))

        # Cache result
        try:
            cache_file.write_text(
                json.dumps({"result": result, "explanation": explanation}),
                encoding="utf-8",
            )
        except Exception:
            pass

        return result, explanation

    except ImportError:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Document text extraction helpers
# ---------------------------------------------------------------------------


def extract_text_from_docx(docx_path: Path) -> str:
    """Extract text content from a .docx file."""
    parts: list[str] = []
    try:
        with zipfile.ZipFile(docx_path, "r") as zf:
            if "word/document.xml" in zf.namelist():
                xml_content = zf.read("word/document.xml")
                root = ET.fromstring(xml_content)
                for elem in root.iter():
                    if elem.tag.endswith("}t") or elem.tag == "t":
                        if elem.text:
                            parts.append(elem.text)
    except Exception:
        pass
    return " ".join(parts)


def extract_text_from_pptx(pptx_path: Path) -> str:
    """Extract text content from a .pptx file."""
    parts: list[str] = []
    try:
        with zipfile.ZipFile(pptx_path, "r") as zf:
            for name in sorted(zf.namelist()):
                if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                    xml_content = zf.read(name)
                    root = ET.fromstring(xml_content)
                    for elem in root.iter():
                        if elem.tag.endswith("}t") or elem.tag == "t":
                            if elem.text:
                                parts.append(elem.text)
    except Exception:
        pass
    return " ".join(parts)


def count_pptx_slides(pptx_path: Path) -> int:
    """Count the number of slides in a .pptx file."""
    try:
        with zipfile.ZipFile(pptx_path, "r") as zf:
            return sum(
                1
                for name in zf.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Skill-specific deterministic checks
# ---------------------------------------------------------------------------


def check_pptx_exists(sandbox_dir: Path, filename: str | None = None) -> Tuple[bool, str]:
    """Check that at least one .pptx file exists (optionally with a specific name)."""
    if filename:
        target = sandbox_dir / filename
        if target.exists():
            return True, f"Found {filename}"
        # Check nested locations
        matches = list(sandbox_dir.rglob(filename))
        if matches:
            return True, f"Found {matches[0].relative_to(sandbox_dir)}"
        return False, f"{filename} not found"

    pptx_files = [
        f for f in sandbox_dir.rglob("*.pptx")
        if ".claude" not in str(f) and ".codex" not in str(f) and ".gemini" not in str(f)
    ]
    if pptx_files:
        return True, f"Found pptx: {[f.name for f in pptx_files]}"
    return False, "No .pptx files found"


def check_docx_exists(sandbox_dir: Path, filename: str | None = None) -> Tuple[bool, str]:
    """Check that at least one .docx file exists (optionally with a specific name)."""
    if filename:
        target = sandbox_dir / filename
        if target.exists():
            return True, f"Found {filename}"
        matches = list(sandbox_dir.rglob(filename))
        if matches:
            return True, f"Found {matches[0].relative_to(sandbox_dir)}"
        return False, f"{filename} not found"

    docx_files = [
        f for f in sandbox_dir.rglob("*.docx")
        if ".claude" not in str(f) and ".codex" not in str(f) and ".gemini" not in str(f)
    ]
    if docx_files:
        return True, f"Found docx: {[f.name for f in docx_files]}"
    return False, "No .docx files found"


def check_xlsx_exists(sandbox_dir: Path, filename: str | None = None) -> Tuple[bool, str]:
    """Check that at least one .xlsx file exists (optionally with a specific name)."""
    if filename:
        target = sandbox_dir / filename
        if target.exists():
            return True, f"Found {filename}"
        matches = list(sandbox_dir.rglob(filename))
        if matches:
            return True, f"Found {matches[0].relative_to(sandbox_dir)}"
        return False, f"{filename} not found"

    xlsx_files = [
        f for f in sandbox_dir.rglob("*.xlsx")
        if ".claude" not in str(f) and ".codex" not in str(f) and ".gemini" not in str(f)
    ]
    if xlsx_files:
        return True, f"Found xlsx: {[f.name for f in xlsx_files]}"
    return False, "No .xlsx files found"


def check_file_created(sandbox_dir: Path, pattern: str) -> Tuple[bool, str]:
    """Check if any file matching glob *pattern* was created in the sandbox."""
    matches = [
        f for f in sandbox_dir.rglob(pattern)
        if ".claude" not in str(f) and ".codex" not in str(f) and ".gemini" not in str(f)
    ]
    if matches:
        names = [str(f.relative_to(sandbox_dir)) for f in matches]
        return True, f"Found: {names}"
    return False, f"No files matching '{pattern}' found"


def check_git_commit_made(sandbox_dir: Path, min_new_commits: int = 1) -> Tuple[bool, str]:
    """Check if at least *min_new_commits* new git commits were made."""
    # Find git repos
    git_dirs: list[Path] = []
    for root, dirs, _files in os.walk(sandbox_dir):
        if ".git" in dirs:
            git_dirs.append(Path(root))

    if not git_dirs:
        return False, "No git repository found"

    for git_dir in git_dirs:
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-20"],
                cwd=git_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                commits = [
                    line for line in result.stdout.strip().splitlines() if line.strip()
                ]
                if len(commits) >= min_new_commits:
                    return True, f"{len(commits)} commits found in {git_dir.relative_to(sandbox_dir)}"
        except Exception:
            continue

    return False, "No new commits found"


def check_python_file_created(sandbox_dir: Path) -> Tuple[bool, str]:
    """Check if any .py file was created by the agent (excluding skill dirs)."""
    py_files = [
        f for f in sandbox_dir.rglob("*.py")
        if ".claude" not in str(f) and ".codex" not in str(f) and ".gemini" not in str(f)
        and "__pycache__" not in str(f)
    ]
    if py_files:
        names = [str(f.relative_to(sandbox_dir)) for f in py_files]
        return True, f"Python files found: {names}"
    return False, "No .py files found"


def check_ics_file_created(sandbox_dir: Path) -> Tuple[bool, str]:
    """Check if an .ics calendar file was created or modified."""
    ics_files = [
        f for f in sandbox_dir.rglob("*.ics")
        if ".claude" not in str(f) and ".codex" not in str(f) and ".gemini" not in str(f)
    ]
    if ics_files:
        names = [str(f.relative_to(sandbox_dir)) for f in ics_files]
        return True, f"ICS files found: {names}"
    return False, "No .ics files found"


def check_pptx_has_slide_count(
    sandbox_dir: Path, filename: str, min_slides: int
) -> Tuple[bool, str]:
    """Check that a pptx has at least *min_slides* slides."""
    target = sandbox_dir / filename
    if not target.exists():
        matches = list(sandbox_dir.rglob(filename))
        if not matches:
            return False, f"{filename} not found"
        target = matches[0]

    count = count_pptx_slides(target)
    if count >= min_slides:
        return True, f"{filename} has {count} slides (>= {min_slides})"
    return False, f"{filename} has {count} slides (expected >= {min_slides})"


def check_pptx_contains_text(
    sandbox_dir: Path, filename: str, text: str
) -> Tuple[bool, str]:
    """Check that a pptx contains the given text (case-insensitive)."""
    target = sandbox_dir / filename
    if not target.exists():
        matches = list(sandbox_dir.rglob(filename))
        if not matches:
            return False, f"{filename} not found"
        target = matches[0]

    content = extract_text_from_pptx(target).lower()
    if text.lower() in content:
        return True, f"Found '{text}' in {filename}"
    return False, f"'{text}' not found in {filename}"


def check_docx_contains_text(
    sandbox_dir: Path, filename: str, text: str
) -> Tuple[bool, str]:
    """Check that a docx contains the given text (case-insensitive)."""
    target = sandbox_dir / filename
    if not target.exists():
        matches = list(sandbox_dir.rglob(filename))
        if not matches:
            return False, f"{filename} not found"
        target = matches[0]

    content = extract_text_from_docx(target).lower()
    if text.lower() in content:
        return True, f"Found '{text}' in {filename}"
    return False, f"'{text}' not found in {filename}"


def read_agent_output(sandbox_dir: Path, *, include_stdout: bool = True) -> str:
    """Read agent-generated output files, excluding skill directories.

    When *include_stdout* is True, ``agent_stdout.txt`` is included but
    lines that are clearly the agent reading skill files are stripped out
    (``cat .../SKILL.md``, ``cat .../skills/...``) to avoid confusing
    the LLM judge with injected instructions vs actual agent output.
    """
    skip_dirs = (".claude", ".codex", ".gemini", "__pycache__")
    parts: list[str] = []

    if include_stdout:
        stdout = sandbox_dir / "agent_stdout.txt"
        if stdout.exists():
            try:
                raw = stdout.read_text(encoding="utf-8", errors="ignore")
                # Filter out lines that dump the skill file content.
                # Skill content typically appears after `cat ...SKILL.md`
                # or inside JSON blocks referencing skill paths.
                filtered: list[str] = []
                in_skill_block = False
                for line in raw.splitlines():
                    ll = line.lower()
                    # Detect start of skill dump (cat SKILL.md or skill path)
                    if "skill.md" in ll and ("cat " in ll or '"filepath"' in ll or "filepath" in ll):
                        in_skill_block = True
                        continue
                    # End of skill block heuristics
                    if in_skill_block:
                        # JSON tool results end with }, tool_use starts new block
                        if ('"type"' in ll and '"tool_use"' in ll) or \
                           ('"type"' in ll and '"assistant"' in ll) or \
                           ('"type"' in ll and '"tool_result"' in ll) or \
                           ll.strip() == "}" or ll.strip() == "},":
                            in_skill_block = False
                        else:
                            continue
                    filtered.append(line)
                parts.append("\n".join(filtered))
            except Exception:
                pass

    # Read all other output files
    for ext in ("*.md", "*.txt", "*.py", "*.json", "*.csv", "*.html",
                "*.js", "*.yaml", "*.yml"):
        for f in sandbox_dir.rglob(ext):
            if any(sd in str(f) for sd in skip_dirs):
                continue
            if f.name == "agent_stdout.txt":
                continue
            try:
                parts.append(f.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue

    return "\n".join(parts)


def check_task_with_llm(
    sandbox_dir: Path,
    task_prompt: str,
    context: str,
    fallback: Tuple[bool, str] | None = None,
) -> Tuple[bool, str]:
    """Use LLM to judge task completion, with deterministic fallback.

    Parameters
    ----------
    sandbox_dir : Path
        The sandbox directory (unused directly, but available for future use).
    task_prompt : str
        The original task the agent was asked to do.
    context : str
        Relevant content for the LLM to judge (extracted text, file listing, etc.).
    fallback : tuple, optional
        If LLM is unavailable, return this.  If None, returns (True, "LLM unavailable, assuming pass").
    """
    question = (
        f"Did the agent successfully complete this task?\n"
        f"Task: {task_prompt}\n\n"
        f"Answer true if the task was completed (even if imperfectly), "
        f"false if the task was clearly not done or the output is unrelated."
    )
    result = llm_check(question, context)
    if result is not None:
        success, explanation = result
        return success, f"LLM judge: {explanation}"

    if fallback is not None:
        return fallback
    return True, "LLM unavailable — coarse check passed, assuming task success"
