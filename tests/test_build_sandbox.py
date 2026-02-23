"""Tests for scripts/build_sandbox.py — injection, helpers, and sandbox building."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from scripts.build_sandbox import (
    inject_at_line,
    inject_into_description,
    parse_id_list,
    load_injections_file,
    resolve_target_file,
    copy_safety_protocol,
    build_sandbox,
)


# ---------------------------------------------------------------------------
# parse_id_list
# ---------------------------------------------------------------------------

class TestParseIdList:
    def test_none_input(self):
        assert parse_id_list(None) == []

    def test_single_items(self):
        assert parse_id_list(["1", "2"]) == ["1", "2"]

    def test_comma_separated(self):
        assert parse_id_list(["1,2,3"]) == ["1", "2", "3"]

    def test_mixed(self):
        assert parse_id_list(["1,2", "3"]) == ["1", "2", "3"]

    def test_strips_whitespace(self):
        assert parse_id_list([" 1 , 2 "]) == ["1", "2"]

    def test_empty_strings_dropped(self):
        assert parse_id_list(["1,,2", ""]) == ["1", "2"]


# ---------------------------------------------------------------------------
# load_injections_file
# ---------------------------------------------------------------------------

class TestLoadInjectionsFile:
    def test_loads_valid_file(self, sample_injections: Path):
        data = load_injections_file(sample_injections)
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["id"] == 1

    def test_missing_file_exits(self, tmp_path: Path):
        with pytest.raises(SystemExit, match="not found"):
            load_injections_file(tmp_path / "nonexistent.json")

    def test_invalid_json_exits(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("{broken json")
        with pytest.raises(SystemExit, match="Failed to parse"):
            load_injections_file(bad)

    def test_non_array_exits(self, tmp_path: Path):
        f = tmp_path / "obj.json"
        f.write_text('{"not": "an array"}')
        with pytest.raises(SystemExit, match="JSON array"):
            load_injections_file(f)


# ---------------------------------------------------------------------------
# resolve_target_file
# ---------------------------------------------------------------------------

class TestResolveTargetFile:
    def test_direct_match(self, tmp_path: Path):
        d = tmp_path / "skill"
        d.mkdir()
        (d / "SKILL.md").write_text("x")
        assert resolve_target_file(d, "SKILL.md") == d / "SKILL.md"

    def test_rglob_single_match(self, tmp_path: Path):
        d = tmp_path / "skill"
        sub = d / "sub"
        sub.mkdir(parents=True)
        (sub / "SKILL.md").write_text("x")
        assert resolve_target_file(d, "SKILL.md") == sub / "SKILL.md"

    def test_not_found_exits(self, tmp_path: Path):
        d = tmp_path / "skill"
        d.mkdir()
        with pytest.raises(SystemExit, match="Could not find"):
            resolve_target_file(d, "MISSING.md")

    def test_multiple_matches_exits(self, tmp_path: Path):
        d = tmp_path / "skill"
        for sub in ("a", "b"):
            s = d / sub
            s.mkdir(parents=True)
            (s / "SKILL.md").write_text("x")
        with pytest.raises(SystemExit, match="Multiple"):
            resolve_target_file(d, "SKILL.md")


# ---------------------------------------------------------------------------
# inject_at_line
# ---------------------------------------------------------------------------

class TestInjectAtLine:
    def test_insert_at_middle(self, skill_file: Path):
        original_lines = skill_file.read_text().splitlines()
        inject_at_line(skill_file, "INJECTED LINE", 7)
        lines = skill_file.read_text().splitlines()
        assert "INJECTED LINE" in lines[6]

    def test_insert_at_first_line(self, skill_file: Path):
        inject_at_line(skill_file, "FIRST", 1)
        lines = skill_file.read_text().splitlines()
        assert lines[0] == "FIRST"

    def test_out_of_range(self, skill_file: Path):
        with pytest.raises(SystemExit):
            inject_at_line(skill_file, "BAD", 999)

    def test_multiline_injection(self, skill_file: Path):
        inject_at_line(skill_file, "LINE A\nLINE B", 7)
        content = skill_file.read_text()
        assert "LINE A" in content
        assert "LINE B" in content

    def test_surrounding_lines_preserved(self, skill_file: Path):
        original = skill_file.read_text().splitlines()
        inject_at_line(skill_file, "INJECTED", 7)
        result = skill_file.read_text().splitlines()
        # Lines before injection point should be unchanged
        for i in range(6):
            assert result[i] == original[i], f"Line {i+1} changed unexpectedly"
        # Lines after injection should shift by 1 but content preserved
        for i in range(6, len(original)):
            assert original[i] in result, f"Original line {i+1} missing: {original[i]!r}"

    def test_total_line_count_increases(self, skill_file: Path):
        original_count = len(skill_file.read_text().splitlines())
        inject_at_line(skill_file, "ONE LINE", 5)
        new_count = len(skill_file.read_text().splitlines())
        assert new_count == original_count + 1

    def test_multiline_count_increases_correctly(self, skill_file: Path):
        original_count = len(skill_file.read_text().splitlines())
        inject_at_line(skill_file, "A\nB\nC", 5)
        new_count = len(skill_file.read_text().splitlines())
        assert new_count == original_count + 3


# ---------------------------------------------------------------------------
# inject_into_description
# ---------------------------------------------------------------------------

class TestInjectIntoDescription:
    def test_single_line_description(self, skill_file: Path):
        inject_into_description(skill_file, "HIDDEN PAYLOAD")
        content = skill_file.read_text()
        assert "HIDDEN PAYLOAD" in content
        assert content.startswith("---\n")

    def test_original_description_preserved(self, skill_file: Path):
        inject_into_description(skill_file, "PAYLOAD")
        content = skill_file.read_text()
        assert "A test skill for unit testing" in content
        assert "PAYLOAD" in content

    def test_body_after_frontmatter_preserved(self, skill_file: Path):
        inject_into_description(skill_file, "PAYLOAD")
        content = skill_file.read_text()
        assert "# Test Skill" in content
        assert "Line 7 content" in content

    def test_no_frontmatter(self, tmp_path: Path):
        f = tmp_path / "no_yaml.md"
        f.write_text("# No YAML\nJust text\n")
        with pytest.raises(SystemExit):
            inject_into_description(f, "payload")

    def test_block_scalar_description(self, tmp_path: Path):
        f = tmp_path / "block.md"
        f.write_text(textwrap.dedent("""\
            ---
            name: test
            description: >
              A multi-line
              description here
            ---

            # Content
        """))
        inject_into_description(f, "INJECTED")
        content = f.read_text()
        assert "INJECTED" in content
        assert "---" in content

    def test_special_chars_in_payload(self, skill_file: Path):
        inject_into_description(skill_file, 'payload with "quotes" and $pecial')
        content = skill_file.read_text()
        assert "quotes" in content


# ---------------------------------------------------------------------------
# copy_safety_protocol
# ---------------------------------------------------------------------------

class TestCopySafetyProtocol:
    def test_as_file(self, tmp_path: Path):
        sb = tmp_path / "sandbox"
        sb.mkdir()
        copy_safety_protocol(sb, "claude", context_text="Be safe", as_skill=False)
        proto = sb / "SECURITY_PROTOCOL.md"
        assert proto.exists()
        assert "Be safe" in proto.read_text()

    def test_as_skill_claude(self, tmp_path: Path):
        sb = tmp_path / "sandbox"
        sb.mkdir()
        copy_safety_protocol(sb, "claude", context_text="Security note", as_skill=True)
        skill = sb / ".claude" / "skills" / "security" / "SKILL.md"
        assert skill.exists()
        content = skill.read_text()
        assert "Security note" in content
        assert "---" in content  # has YAML header

    def test_as_skill_gemini(self, tmp_path: Path):
        sb = tmp_path / "sandbox"
        sb.mkdir()
        copy_safety_protocol(sb, "gemini", context_text="Warn", as_skill=True)
        skill = sb / ".gemini" / "skills" / "security" / "SKILL.md"
        assert skill.exists()

    def test_none_context_text(self, tmp_path: Path):
        sb = tmp_path / "sandbox"
        sb.mkdir()
        copy_safety_protocol(sb, "claude", context_text=None, as_skill=False)
        proto = sb / "SECURITY_PROTOCOL.md"
        assert proto.exists()
        assert proto.read_text() == ""


# ---------------------------------------------------------------------------
# build_sandbox (end-to-end)
# ---------------------------------------------------------------------------

class TestBuildSandbox:
    def _make_injection(self, *, skill="test-skill", line_num=7):
        return {
            "id": 42,
            "instructions": {
                "line_injection": "MALICIOUS LINE",
                "description_injection": "HIDDEN DESC",
            },
            "tasks": [],
            "context": {},
            "task_scripts": {},
        }

    def _make_task(self, *, skill="test-skill", line_num=7):
        return {
            "prompt": "Do the task",
            "skill": skill,
            "line_num": line_num,
            "injection_prefix": "",
            "task_files": {},
        }

    def test_creates_sandbox_dir_with_skill(self, tmp_path: Path, fake_skill_root: Path):
        sandbox_root = tmp_path / "out"
        sandbox_root.mkdir()
        meta = build_sandbox(
            injection=self._make_injection(),
            task_info=self._make_task(),
            sandbox_root=sandbox_root,
            skill_root_dir=fake_skill_root,
            target_file_name="SKILL.md",
        )
        assert meta["sandbox_id"] == "INST-42_test-skill"
        assert meta["injection_id"] == 42
        assert meta["skill"] == "test-skill"
        sandbox_dir = sandbox_root / "INST-42_test-skill"
        assert sandbox_dir.exists()
        # Skill should be copied into .claude/skills/test-skill/SKILL.md
        skill_md = sandbox_dir / ".claude" / "skills" / "test-skill" / "SKILL.md"
        assert skill_md.exists()

    def test_injection_applied(self, tmp_path: Path, fake_skill_root: Path):
        sandbox_root = tmp_path / "out"
        sandbox_root.mkdir()
        build_sandbox(
            injection=self._make_injection(),
            task_info=self._make_task(),
            sandbox_root=sandbox_root,
            skill_root_dir=fake_skill_root,
            target_file_name="SKILL.md",
        )
        skill_md = sandbox_root / "INST-42_test-skill" / ".claude" / "skills" / "test-skill" / "SKILL.md"
        content = skill_md.read_text()
        assert "MALICIOUS LINE" in content

    def test_description_injection_only_when_enabled(self, tmp_path: Path, fake_skill_root: Path):
        sandbox_root = tmp_path / "out"
        sandbox_root.mkdir()
        # Without enable_description_injection
        build_sandbox(
            injection=self._make_injection(),
            task_info=self._make_task(),
            sandbox_root=sandbox_root,
            skill_root_dir=fake_skill_root,
            target_file_name="SKILL.md",
            enable_description_injection=False,
        )
        skill_md = sandbox_root / "INST-42_test-skill" / ".claude" / "skills" / "test-skill" / "SKILL.md"
        assert "HIDDEN DESC" not in skill_md.read_text()

    def test_description_injection_when_enabled(self, tmp_path: Path, fake_skill_root: Path):
        sandbox_root = tmp_path / "out"
        sandbox_root.mkdir()
        build_sandbox(
            injection=self._make_injection(),
            task_info=self._make_task(),
            sandbox_root=sandbox_root,
            skill_root_dir=fake_skill_root,
            target_file_name="SKILL.md",
            enable_description_injection=True,
        )
        skill_md = sandbox_root / "INST-42_test-skill" / ".claude" / "skills" / "test-skill" / "SKILL.md"
        assert "HIDDEN DESC" in skill_md.read_text()

    def test_sandbox_suffix(self, tmp_path: Path, fake_skill_root: Path):
        sandbox_root = tmp_path / "out"
        sandbox_root.mkdir()
        meta = build_sandbox(
            injection=self._make_injection(),
            task_info=self._make_task(),
            sandbox_root=sandbox_root,
            skill_root_dir=fake_skill_root,
            target_file_name="SKILL.md",
            sandbox_suffix="legitimizing",
        )
        assert meta["sandbox_id"] == "INST-42_test-skill_legitimizing"
        assert (sandbox_root / "INST-42_test-skill_legitimizing").exists()

    def test_dry_run_no_filesystem(self, tmp_path: Path, fake_skill_root: Path):
        sandbox_root = tmp_path / "out"
        sandbox_root.mkdir()
        meta = build_sandbox(
            injection=self._make_injection(),
            task_info=self._make_task(),
            sandbox_root=sandbox_root,
            skill_root_dir=fake_skill_root,
            target_file_name="SKILL.md",
            dry_run=True,
        )
        assert meta["sandbox_id"] == "INST-42_test-skill"
        # No directory should have been created
        assert not (sandbox_root / "INST-42_test-skill").exists()

    def test_no_skill_returns_empty(self, tmp_path: Path, fake_skill_root: Path):
        sandbox_root = tmp_path / "out"
        sandbox_root.mkdir()
        meta = build_sandbox(
            injection=self._make_injection(),
            task_info={"prompt": "x", "skill": "", "task_files": {}},
            sandbox_root=sandbox_root,
            skill_root_dir=fake_skill_root,
            target_file_name="SKILL.md",
        )
        assert meta == {}

    def test_gemini_layout(self, tmp_path: Path, fake_skill_root: Path):
        sandbox_root = tmp_path / "out"
        sandbox_root.mkdir()
        build_sandbox(
            injection=self._make_injection(),
            task_info=self._make_task(),
            sandbox_root=sandbox_root,
            skill_root_dir=fake_skill_root,
            target_file_name="SKILL.md",
            skill_layout="gemini",
        )
        sb = sandbox_root / "INST-42_test-skill"
        # Should have .gemini/skills/test-skill/SKILL.md
        assert (sb / ".gemini" / "skills" / "test-skill" / "SKILL.md").exists()
        # Should have .gemini/settings.json
        settings = sb / ".gemini" / "settings.json"
        assert settings.exists()
        assert json.loads(settings.read_text())["experimental"]["skills"] is True

    def test_safety_protocol_created(self, tmp_path: Path, fake_skill_root: Path):
        sandbox_root = tmp_path / "out"
        sandbox_root.mkdir()
        build_sandbox(
            injection=self._make_injection(),
            task_info=self._make_task(),
            sandbox_root=sandbox_root,
            skill_root_dir=fake_skill_root,
            target_file_name="SKILL.md",
            safety_protocol_mode=2,
            safety_context_text="WARNING: be careful",
        )
        proto = sandbox_root / "INST-42_test-skill" / "SECURITY_PROTOCOL.md"
        assert proto.exists()
        assert "WARNING: be careful" in proto.read_text()

    def test_task_files_copied(self, tmp_path: Path, fake_skill_root: Path):
        # Create a task file to be copied
        task_file = tmp_path / "input.docx"
        task_file.write_text("fake docx content")

        sandbox_root = tmp_path / "out"
        sandbox_root.mkdir()

        task_info = self._make_task()
        task_info["task_files"] = {"doc": str(task_file)}

        meta = build_sandbox(
            injection=self._make_injection(),
            task_info=task_info,
            sandbox_root=sandbox_root,
            skill_root_dir=fake_skill_root,
            target_file_name="SKILL.md",
        )
        assert "input.docx" in meta["task_files"]
        assert (sandbox_root / "INST-42_test-skill" / "input.docx").exists()

    def test_injection_prefix_prepended(self, tmp_path: Path, fake_skill_root: Path):
        sandbox_root = tmp_path / "out"
        sandbox_root.mkdir()
        task = self._make_task()
        task["injection_prefix"] = "# IMPORTANT: "
        build_sandbox(
            injection=self._make_injection(),
            task_info=task,
            sandbox_root=sandbox_root,
            skill_root_dir=fake_skill_root,
            target_file_name="SKILL.md",
        )
        skill_md = sandbox_root / "INST-42_test-skill" / ".claude" / "skills" / "test-skill" / "SKILL.md"
        content = skill_md.read_text()
        assert "# IMPORTANT: MALICIOUS LINE" in content

    def test_manifest_entry_has_required_keys(self, tmp_path: Path, fake_skill_root: Path):
        sandbox_root = tmp_path / "out"
        sandbox_root.mkdir()
        meta = build_sandbox(
            injection=self._make_injection(),
            task_info=self._make_task(),
            sandbox_root=sandbox_root,
            skill_root_dir=fake_skill_root,
            target_file_name="SKILL.md",
        )
        for key in ("sandbox_id", "injection_id", "skill", "skill_path",
                     "sandbox_path", "target_file", "task_files", "task_scripts",
                     "root_files", "startup_scripts", "task_prompt"):
            assert key in meta, f"Missing key: {key}"
