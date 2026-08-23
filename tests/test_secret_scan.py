"""Tests for the agent-agnostic secret scanner (live subprocess entrypoint)."""

from __future__ import annotations

import io
import json
import runpy
import subprocess
import sys
from collections.abc import Mapping
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

import scripts.secret_scan as scanner
from scripts.bootstrap.canonical_json import decode_json

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNER = REPO_ROOT / "scripts" / "secret_scan.py"

# Import the module in-process so coverage is captured for the universal core
# and `main`; the subprocess tests below exercise the real CLI entrypoint.


def test_scan_text_flags_known_patterns() -> None:
    assert scanner.scan_text("key = 'AKIAIOSFODNN7EXAMPLE'") is not None
    assert scanner.scan_text("DB_PASSWORD='supersecretpassword123'") is not None
    assert scanner.scan_text("print('hello')") is None


def test_flatten_json_concatenates_every_string_leaf() -> None:
    value = decode_json(
        json.dumps(
            {
                "tool_input": {
                    "file_path": "a.env",
                    "new_string": "DB_PASSWORD='y'",
                    "list": ["one", "two"],
                },
                "nested": {"deep": "secret=abc"},
                "flag": False,
                "count": 3,
                "empty": None,
            }
        ).encode("utf-8")
    )
    flattened = scanner.flatten_json(value)
    assert "DB_PASSWORD='y'" in flattened
    assert "secret=abc" in flattened
    assert "one" in flattened and "two" in flattened


def test_flatten_json_excludes_removed_content() -> None:
    value = decode_json(
        json.dumps(
            {
                "tool_input": {
                    "old_string": "DB_PASSWORD='supersecretpassword123'",
                    "new_string": "DB_PASSWORD=''",
                }
            }
        ).encode("utf-8")
    )
    flattened = scanner.flatten_json(value)
    assert "DB_PASSWORD='supersecretpassword123'" not in flattened
    assert "DB_PASSWORD=''" in flattened


def test_flatten_json_handles_float_leaves() -> None:
    value = decode_json(json.dumps({"tool_input": {"position": 1.5}}).encode("utf-8"))
    assert scanner.flatten_json(value) == ""


def test_main_blocks_on_suspected_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "tool_name": "Write",
                    "tool_input": {"content": "key = 'AKIAIOSFODNN7EXAMPLE'"},
                }
            ),
        ),
    )
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        assert scanner.main() == 2


def test_main_allows_benign_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {"tool_name": "Write", "tool_input": {"content": "print('hello')\n"}}
            ),
        ),
    )
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        assert scanner.main() == 0


def test_main_allows_empty_and_malformed_input(monkeypatch: pytest.MonkeyPatch) -> None:
    for payload in ("", "   ", "not json"):
        monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            assert scanner.main() == 0


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


def test_allows_secret_removal_via_old_string() -> None:
    # Removing a secret (the secret lives only in old_string, the text being
    # deleted) must not be blocked; only prospective content is scanned.
    event = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "a.env",
            "old_string": "DB_PASSWORD='supersecretpassword123'\n",
            "new_string": "DB_PASSWORD=''\n",
        },
    }
    result = _run(event)
    assert result.returncode == 0, result.stderr


def test_cli_entrypoint_blocks_on_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps({"tool_input": {"content": "AKIAIOSFODNN7EXAMPLE"}}),
        ),
    )
    with pytest.raises(SystemExit) as exc:
        _ = runpy.run_path(str(SCANNER), run_name="__main__")
    assert exc.value.code == 2


def test_cli_entrypoint_allows_benign(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps({"tool_input": {"content": "print('hi')\n"}}),
        ),
    )
    with pytest.raises(SystemExit) as exc:
        _ = runpy.run_path(str(SCANNER), run_name="__main__")
    assert exc.value.code == 0
    result = subprocess.run(
        [sys.executable, str(SCANNER)],
        input="not json",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
