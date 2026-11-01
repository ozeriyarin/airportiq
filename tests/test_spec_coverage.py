"""Every numbered acceptance criterion in agent-os/specs/<date>-<slug>/spec.md has a test named
test_criterion_<n>_<slug> in tests/test_<slug_with_underscores>.py, so two specs' numbers never collide.

A spec may opt out while in progress by listing its folder name in UNIMPLEMENTED; remove it when its tests land.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import ROOT

SPECS = ROOT / "agent-os" / "specs"
TESTS = Path(__file__).parent
UNIMPLEMENTED: set[str] = set()

CRITERION = re.compile(r"^\s*(\d+)\.\s+\S", re.MULTILINE)
SPEC_FOLDER = re.compile(r"^\d{4}-\d{2}-\d{2}-(.+)$")


def criteria_of(spec: Path) -> list[int]:
    text = spec.read_text(encoding="utf-8")
    m = re.search(r"^##\s+Acceptance criteria\s*$(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    return [int(n) for n in CRITERION.findall(m.group(1))] if m else []


def criterion_test_file(spec_dir: Path, tests_dir: Path) -> Path:
    m = SPEC_FOLDER.match(spec_dir.name)
    slug = m.group(1) if m else spec_dir.name
    return tests_dir / f"test_{slug.replace('-', '_')}.py"


def missing_criteria(specs_dir: Path, tests_dir: Path, skip: set[str] = frozenset()) -> list[str]:
    missing: list[str] = []
    for spec in sorted(specs_dir.glob("*/spec.md")):
        if spec.parent.name in skip:
            continue
        test_file = criterion_test_file(spec.parent, tests_dir)
        text = test_file.read_text(encoding="utf-8") if test_file.exists() else ""
        for n in criteria_of(spec):
            if not re.search(rf"def test_criterion_{n}_\w+", text):
                missing.append(f"{spec.parent.name}: criterion {n} (expected in {test_file.name})")
    return missing


def test_every_spec_criterion_has_a_named_test():
    missing = missing_criteria(SPECS, TESTS, UNIMPLEMENTED)
    assert not missing, "criteria without a test:\n" + "\n".join(missing)
