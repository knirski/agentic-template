#!/usr/bin/env python3
"""Emit the semantic-release eligibility verdict for the validated commit.

The release job keeps a last-moment branch-tip check: semantic-release runs
only when the validated commit is still the tip of the default branch.  The
verdict is appended to ``GITHUB_OUTPUT`` when that file is provided, so the
publishing step can gate on ``steps.release-eligibility.outputs.eligible``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_GH_TIMEOUT_SECONDS = 30


def main() -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    sha = os.environ.get("GITHUB_SHA", "")
    token = os.environ.get("GH_TOKEN", "")
    if not repository or not sha or not token:
        print(
            "release eligibility requires GITHUB_REPOSITORY, GITHUB_SHA, and GH_TOKEN",
            file=sys.stderr,
        )
        return 2
    if _REPOSITORY_PATTERN.fullmatch(repository) is None:
        print(
            f"GITHUB_REPOSITORY is not an owner/repository pair: {repository!r}",
            file=sys.stderr,
        )
        return 2
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{repository}/git/ref/heads/main",
                "--jq",
                ".object.sha",
            ],
            env={**os.environ, "GH_TOKEN": token},
            capture_output=True,
            text=True,
            check=False,
            timeout=_GH_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"gh api failed: {error}", file=sys.stderr)
        return 2
    if result.returncode != 0:
        print(f"gh api failed: {result.stderr.strip()}", file=sys.stderr)
        return 2
    eligible = "true" if result.stdout.strip() == sha else "false"
    if eligible == "true":
        print("Release eligible.")
    else:
        print(
            "Skipping release because this validated commit is no longer the main branch tip."
        )
    output = os.environ.get("GITHUB_OUTPUT", "")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            _ = handle.write(f"eligible={eligible}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
