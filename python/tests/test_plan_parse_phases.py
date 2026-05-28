"""Tests for _parse_plan_phases: parsing ## Phases section from plan.md."""
from __future__ import annotations

from agent_loop.cli import _parse_plan_phases


_DETAILED_PLAN = """\
# Plan: Add caching

## Goal
Speed things up.

## Phases
1. **Parse input** -- Extract tokens from raw text
   - Target files: `src/parser.py`, `src/tokenizer.py`
   - Before/after: New module for parsing.
   - Testing:
     - What to test: tokenizer output
     - How to verify: `pytest src/tests/test_parser.py` -- all tests pass
   - Acceptance criteria:
     - [ ] pytest src/tests/test_parser.py passes
     - [ ] No regressions in src/tokenizer.py
2. **Build cache layer** -- Add in-memory LRU cache
   - Target files: `src/cache.py`
   - Testing:
     - How to verify: `python -m pytest src/tests/test_cache.py -q` -- 0 failures
   - Acceptance criteria:
     - [ ] Cache hit rate > 80%
     - [x] Existing tests still pass

## Example Scenarios
This section should not be parsed.
"""

_ONE_LINER_PLAN = """\
# Plan: Quick fix

## Phases
1. **Fix login bug** -- Correct auth token validation
2. **Update docs** -- Reflect new auth flow

## Notes
Nothing special.
"""

_NO_PHASES_PLAN = """\
# Plan: No phases here

## Goal
Some goal.

## Tasks
1. Do something.
"""


def test_parse_plan_phases_detailed_form() -> None:
    result = _parse_plan_phases(_DETAILED_PLAN)
    assert result is not None
    assert len(result) == 2

    ph1 = result[0]
    assert ph1["phase_n"] == 1
    assert ph1["title"] == "Parse input"
    assert ph1["objective"] == "Extract tokens from raw text"
    assert ph1["target_files"] == ["src/parser.py", "src/tokenizer.py"]
    assert ph1["testing"]["command"] == "pytest src/tests/test_parser.py"
    assert ph1["testing"]["expected"] == "all tests pass"
    # acceptance_criteria items must not have [ ] prefix
    for item in ph1["acceptance_criteria"]:
        assert not item.startswith("["), f"Unexpected prefix in: {item!r}"
    assert any("pytest" in item for item in ph1["acceptance_criteria"])

    ph2 = result[1]
    assert ph2["phase_n"] == 2
    assert ph2["title"] == "Build cache layer"
    assert ph2["target_files"] == ["src/cache.py"]
    assert ph2["testing"]["command"] == "python -m pytest src/tests/test_cache.py -q"
    assert len(ph2["acceptance_criteria"]) == 2
    for item in ph2["acceptance_criteria"]:
        assert not item.startswith("["), f"Unexpected prefix in: {item!r}"


def test_parse_plan_phases_one_liner_form() -> None:
    result = _parse_plan_phases(_ONE_LINER_PLAN)
    assert result is not None
    assert len(result) == 2

    ph1 = result[0]
    assert ph1["phase_n"] == 1
    assert ph1["title"] == "Fix login bug"
    assert ph1["objective"] == "Correct auth token validation"
    assert ph1["target_files"] == []
    assert ph1["acceptance_criteria"] == []
    assert ph1["testing"] == {"command": "", "expected": ""}
    assert ph1["out_of_scope"] == []
    assert ph1["notes"] == ""

    ph2 = result[1]
    assert ph2["phase_n"] == 2
    assert ph2["title"] == "Update docs"
    assert ph2["objective"] == "Reflect new auth flow"
    assert ph2["target_files"] == []
    assert ph2["testing"] == {"command": "", "expected": ""}


def test_parse_plan_phases_without_phases_section() -> None:
    result = _parse_plan_phases(_NO_PHASES_PLAN)
    assert result is None
