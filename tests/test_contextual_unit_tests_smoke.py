"""Smoke test: every test_contextual_N.py imports and exposes the expected API."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

CONTEXTUAL_DIR = Path(__file__).resolve().parent.parent / "data" / "instruction_unit_tests" / "contextual"
EXPECTED_ATTRS = ("INJECTION_ID", "INJECTION_TITLE", "TEST_DESCRIPTION", "ATTACK_TYPE", "test_attack")
EXPECTED_IDS = list(range(1, 49))


def _all_test_files() -> list[Path]:
    return sorted(CONTEXTUAL_DIR.glob("test_contextual_*.py"))


def test_one_test_file_per_injection():
    files = _all_test_files()
    found_ids = sorted(int(f.stem.removeprefix("test_contextual_")) for f in files)
    assert found_ids == EXPECTED_IDS, f"missing {set(EXPECTED_IDS) - set(found_ids)}"


@pytest.mark.parametrize("test_file", _all_test_files(), ids=lambda p: p.stem)
def test_module_imports_and_exposes_api(test_file: Path):
    spec = importlib.util.spec_from_file_location(test_file.stem, test_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for attr in EXPECTED_ATTRS:
        assert hasattr(mod, attr), f"{test_file.name} missing {attr}"
    expected_id = int(test_file.stem.removeprefix("test_contextual_"))
    assert mod.INJECTION_ID == expected_id
    assert callable(mod.test_attack)
    sibling_name = f"test_contextual_{expected_id}"
    assert callable(getattr(mod, sibling_name, None)), f"{test_file.name} missing {sibling_name}()"
