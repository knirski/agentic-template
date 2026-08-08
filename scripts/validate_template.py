#!/usr/bin/env python3
"""Validate the template-owned file and skill contract."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from scripts.bootstrap import template_contract  # noqa: E402


def validate_contract(
    root: Path, skill_texts: tuple[tuple[Path, str], ...]
) -> tuple[str, ...]:
    """Evaluate an observed template through the shared pure policy."""
    present_files = tuple(
        relative
        for relative in template_contract.REQUIRED_FILES
        if (root / relative).is_file()
    )
    observed_skills = tuple(
        (path.relative_to(root).as_posix(), text) for path, text in skill_texts
    )
    return template_contract.required_contract_failures(present_files, observed_skills)


def main(argv: list[str]) -> int:
    if argv:
        print("usage: scripts/validate_template.py", file=sys.stderr)
        return 2
    skill_paths = sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md"))
    skill_texts = tuple(
        (path, path.read_text(encoding="utf-8")) for path in skill_paths
    )
    failures = validate_contract(ROOT, skill_texts)
    for failure in failures:
        print(
            f"TEMPLATE_CONTRACT_ERROR: {failure}; next: restore the template contract",
            file=sys.stderr,
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
