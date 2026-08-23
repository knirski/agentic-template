"""Tests for the agent-agnostic secret scanner (live subprocess entrypoint)."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNER = REPO_ROOT / "scripts" / "secret_scan.py"


def _run(event: Mapping[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCANNER)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        check=False,
    )


def test_allows_benign_write() -> None:
    event = {
        "tool_name": "Write",
        "tool_input": {"file_path": "src/app.py", "content": "print('hello')\n"},
    }
    result = _run(event)
    assert result.returncode == 0, result.stderr


def test_blocks_aws_access_key_anywhere() -> None:
    event = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "src/creds.py",
            "content": "key = 'AKIAIOSFODNN7EXAMPLE'\n",
        },
    }
    result = _run(event)
    assert result.returncode == 2
    assert "secret" in result.stderr.lower()


def test_blocks_secret_in_edit_new_string() -> None:
    event = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "a.env",
            "old_string": "x",
            "new_string": "DB_PASSWORD='supersecretpassword123'\n",
        },
    }
    result = _run(event)
    assert result.returncode == 2


def test_blocks_secret_in_old_string_too() -> None:
    # Universal scanning flags secrets wherever they appear, including the
    # string being removed; safe, and independent of any agent's event shape.
    event = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "a.env",
            "old_string": "DB_PASSWORD='supersecretpassword123'\n",
            "new_string": "DB_PASSWORD=''\n",
        },
    }
    result = _run(event)
    assert result.returncode == 2


def test_malformed_stdin_allowed() -> None:
    result = subprocess.run(
        [sys.executable, str(SCANNER)],
        input="not json",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
