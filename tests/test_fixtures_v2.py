"""Defect-reproduction fixtures: old suite wrong, new suite right.

Each fixture is a real sandbox from the evidence bundle (path recorded in its
``expected.json``), trimmed to the files a test can actually read.  The point is
to pin *why* each rewrite happened, so a future change that reintroduces the
defect fails here rather than in a 90-minute re-score.

Runnable under pytest or directly:

    python3 tests/test_fixtures_v2.py
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sandboxes"

OLD_SUITE = ROOT / "results_v2026-07-31" / "code" / "data" / "instruction_unit_tests"
NEW_SUITE = ROOT / "data" / "instruction_unit_tests_v2"


def _load_test(suite_dir: Path, injection_id: int, suite: str, tag: str):
    """Import one test module from a suite, isolating sys.path per suite."""
    if suite == "obvious":
        path = suite_dir / "obvious" / f"test_obvious_{injection_id}.py"
    else:
        path = suite_dir / f"test_instruction_{injection_id}.py"
    if not path.exists():
        return None

    saved = list(sys.path)
    # Drop the other suite so its modules are not reused.
    sys.path[:] = [str(suite_dir), str(suite_dir / "obvious")] + [
        p for p in saved if "instruction_unit_tests" not in p]
    dropped = {k: v for k, v in sys.modules.items()
               if k in ("command_history", "task_checks", "transcript",
                        "verdict", "injection_data")}
    for k in dropped:
        del sys.modules[k]
    try:
        spec = importlib.util.spec_from_file_location(f"{tag}_{suite}_{injection_id}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, "test_attack", None)
    finally:
        sys.path[:] = saved
        for k in list(sys.modules):
            if k in ("command_history", "task_checks", "transcript",
                     "verdict", "injection_data"):
                del sys.modules[k]
        sys.modules.update(dropped)


EXPECTED = Path(__file__).resolve().parent / "fixtures" / "expected"


def _cases():
    """Fixture metadata lives *outside* the sandbox directories.

    Keeping ``expected.json`` inside a sandbox made it part of the evidence:
    ``generated_file_contains`` scanned it and matched the attack string quoted
    in the description, so a legitimate-behaviour fixture reported an attack.
    """
    for meta in sorted(EXPECTED.glob("*.json")):
        sandbox = FIXTURES / meta.stem
        if sandbox.is_dir():
            yield sandbox, json.loads(meta.read_text())


def test_fixtures_reproduce_defects():
    failures = []
    checked = 0
    for sandbox, meta in _cases():
        iid, suite = meta["injection_id"], meta["suite"]

        new_fn = _load_test(NEW_SUITE, iid, suite, "new")
        assert new_fn is not None, f"new suite missing test for {iid}"
        got_new = new_fn(sandbox)[0]
        if got_new != meta["new_suite_fires"]:
            failures.append(
                f"{sandbox.name}: new suite fired={got_new}, "
                f"expected {meta['new_suite_fires']} — {meta['why']}")
        checked += 1

        # The old suite is only present when the frozen bundle is available.
        old_fn = _load_test(OLD_SUITE, iid, suite, "old") if OLD_SUITE.exists() else None
        if old_fn is not None:
            got_old = old_fn(sandbox)[0]
            if got_old != meta["old_suite_fires"]:
                failures.append(
                    f"{sandbox.name}: OLD suite fired={got_old}, "
                    f"expected {meta['old_suite_fires']}")

    assert checked, "no fixtures found"
    assert not failures, "\n".join(failures)


def _main() -> int:
    try:
        test_fixtures_reproduce_defects()
    except AssertionError as exc:
        print("FAIL:\n" + str(exc))
        return 1
    n = sum(1 for _ in _cases())
    print(f"{n}/{n} fixtures behave as expected (old wrong, new right)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
