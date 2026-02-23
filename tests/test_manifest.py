"""Tests for manifest loading, sandbox filtering, and ID parsing."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from judges._base import BaseJudge
from experiments._base import ExperimentRunner


class TestParsesSandboxName:
    def test_simple_name(self):
        inj_id, task_idx = BaseJudge.parse_sandbox_name("INST-5_pdf")
        assert inj_id == 5
        assert task_idx is None

    def test_with_task(self):
        inj_id, task_idx = BaseJudge.parse_sandbox_name("INST-12_xlsx_task3")
        assert inj_id == 12
        assert task_idx == 3

    def test_with_suffix(self):
        inj_id, task_idx = BaseJudge.parse_sandbox_name("INST-7_git_legitimizing")
        assert inj_id == 7
        assert task_idx is None

    def test_with_suffix_and_task(self):
        inj_id, task_idx = BaseJudge.parse_sandbox_name("INST-7_git_legitimizing_task2")
        assert inj_id == 7
        assert task_idx == 2


class TestFindSandboxes:
    def test_finds_inst_dirs(self, sample_manifest):
        root = sample_manifest["root"]
        found = BaseJudge.find_sandboxes(root)
        assert len(found) == 2
        assert all(d.name.startswith("INST-") for d in found)

    def test_ignores_non_inst(self, sample_manifest):
        root = sample_manifest["root"]
        (root / "other_dir").mkdir()
        found = BaseJudge.find_sandboxes(root)
        assert len(found) == 2


class TestFilterPolicySandboxes:
    def test_filters_by_suffix(self, tmp_path: Path):
        root = tmp_path / "sandboxes"
        root.mkdir()
        for name in ("INST-1_pdf_legitimizing", "INST-1_pdf_warning", "INST-2_xlsx_legitimizing"):
            sb = root / name
            sb.mkdir()
            (sb / "dummy").write_text("x")

        manifest = {
            "entries": [
                {"sandbox_id": name, "sandbox_path": name}
                for name in ("INST-1_pdf_legitimizing", "INST-1_pdf_warning", "INST-2_xlsx_legitimizing")
            ]
        }
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        runner = ExperimentRunner()
        runner.filter_policy_sandboxes(root, "legitimizing")

        kept = json.loads((root / "manifest.json").read_text())["entries"]
        assert len(kept) == 2
        assert all("legitimizing" in e["sandbox_id"] for e in kept)
        # Warning sandbox should be deleted
        assert not (root / "INST-1_pdf_warning").exists()

    def test_no_match_raises(self, tmp_path: Path):
        root = tmp_path / "empty"
        root.mkdir()
        manifest = {"entries": [{"sandbox_id": "INST-1_pdf", "sandbox_path": "INST-1_pdf"}]}
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        runner = ExperimentRunner()
        with pytest.raises(RuntimeError, match="No sandboxes"):
            runner.filter_policy_sandboxes(root, "nonexistent")
