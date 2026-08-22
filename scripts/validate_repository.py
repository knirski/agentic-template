#!/usr/bin/env python3
"""Run generated-project validation stages with bounded, safe capture."""

from __future__ import annotations

import base64
import hashlib
import subprocess
import sys
import threading
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from scripts.bootstrap.canonical_json import canonical_json  # noqa: E402
from scripts.bootstrap.errors import sanitize_process_error  # noqa: E402
from scripts.bootstrap.validation_presentation import (  # noqa: E402
    ValidationOptions,
    color_enabled,
    parse_options,
    render_usage_error,
    requested_json,
    safe_text,
)
from scripts.bootstrap.validation_program import (  # noqa: E402
    STREAM_PREFIX_LIMIT,
    CapturedStream,
    StageFailed,
    StageLaunchFailed,
    StageObservation,
    StagePassed,
    StageSignalled,
    ValidationProgram,
    stage_exit_code,
)

STAGES = (
    ("template contract", ROOT / "scripts/validate_template.py", True),
    ("project readiness", ROOT / "scripts/check_project_readiness.py", True),
    ("project validation", ROOT / "scripts/validate-project", False),
)


class _Digest(Protocol):
    def update(self, data: bytes, /) -> None: ...

    def hexdigest(self) -> str: ...


class _ReadablePipe(Protocol):
    def read(self, size: int, /) -> bytes: ...


@dataclass(slots=True)
class _StreamCapture:
    total_bytes: int = 0
    digest: _Digest = dataclass_field(default_factory=hashlib.sha256)
    prefix: bytearray = dataclass_field(default_factory=bytearray)

    def consume(self, chunk: bytes) -> None:
        self.total_bytes += len(chunk)
        self.digest.update(chunk)
        remaining = STREAM_PREFIX_LIMIT - len(self.prefix)
        if remaining > 0:
            self.prefix.extend(chunk[:remaining])

    def finish(self) -> CapturedStream:
        return CapturedStream(
            total_bytes=self.total_bytes,
            sha256=self.digest.hexdigest(),
            prefix_base64=base64.b64encode(self.prefix).decode("ascii"),
            truncated=self.total_bytes > len(self.prefix),
        )


def parse_validator_options(argv: list[str]) -> ValidationOptions | None:
    """Keep the aggregate adapter's public parser explicit for library callers."""

    return parse_options(argv)


def stage_command(script: Path, use_python: bool, python_executable: str) -> list[str]:
    return [python_executable, str(script)] if use_python else [str(script)]


def validation_program() -> ValidationProgram:
    return ValidationProgram(tuple(label for label, _, _ in STAGES))


def _capture_pipe(pipe: _ReadablePipe, capture: _StreamCapture) -> None:
    while True:
        chunk = pipe.read(64 * 1024)
        if not chunk:
            return
        capture.consume(chunk)


def run_stage(command: list[str]) -> StageObservation:
    """Launch one stage and count/hash its output while retaining only a prefix."""

    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return StageLaunchFailed(sanitize_process_error(exc))
    stdout_capture = _StreamCapture()
    stderr_capture = _StreamCapture()
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_thread = threading.Thread(
        target=_capture_pipe, args=(process.stdout, stdout_capture), daemon=True
    )
    stderr_thread = threading.Thread(
        target=_capture_pipe, args=(process.stderr, stderr_capture), daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()
    returncode = process.wait()
    stdout_thread.join()
    stderr_thread.join()
    stdout = stdout_capture.finish()
    stderr = stderr_capture.finish()
    if returncode < 0:
        return StageSignalled(-returncode, stdout, stderr)
    if returncode == 0:
        return StagePassed(0, stdout, stderr)
    return StageFailed(returncode, stdout, stderr)


def _stream_document(stream: CapturedStream | None) -> dict[str, object]:
    if stream is None:
        stream = CapturedStream.from_bytes(b"")
    return {
        "total_bytes": stream.total_bytes,
        "sha256": stream.sha256,
        "prefix_base64": stream.prefix_base64,
        "truncated": stream.truncated,
    }


def _stage_document(label: str, observation: StageObservation) -> dict[str, object]:
    common: dict[str, object] = {
        "label": label,
        "exit_code": stage_exit_code(observation),
    }
    match observation:
        case StagePassed():
            common["kind"] = "passed"
        case StageFailed():
            common["kind"] = "failed"
        case StageSignalled(signal=signal):
            common["kind"] = "signalled"
            common["signal"] = signal
        case StageLaunchFailed(error=error):
            common["kind"] = "launch_failed"
            common["error"] = error.kind.value
    common["stdout"] = _stream_document(getattr(observation, "stdout", None))
    common["stderr"] = _stream_document(getattr(observation, "stderr", None))
    return common


def _stream_text(stream: CapturedStream | None) -> str:
    if stream is None:
        return ""
    try:
        data = base64.b64decode(stream.prefix_base64, validate=True)
    except ValueError:
        return "<invalid captured prefix>"
    suffix = "… [truncated]" if stream.truncated else ""
    # ``surrogateescape`` preserves undecodable bytes as U+DCxx, which the
    # shared sanitizer renders as ASCII ``\\udcxx`` escapes rather than a
    # lossy replacement character.
    return safe_text(data.decode("utf-8", "surrogateescape")) + suffix


def _render_text_stage(
    label: str, observation: StageObservation, options: ValidationOptions
) -> None:
    header = f"==> {label}"
    if color_enabled(options, stream=sys.stdout):
        header = f"\033[36m{header}\033[0m"
    if not options.quiet:
        print(header, flush=True)
    stdout = _stream_text(getattr(observation, "stdout", None))
    stderr = _stream_text(getattr(observation, "stderr", None))
    if stdout and not options.quiet:
        print(f"stdout: {stdout}")
    if stderr:
        print(f"stderr: {stderr}", file=sys.stderr)
    if options.explain and not options.quiet:
        document = _stage_document(label, observation)
        print(f"stage: {document['kind']} exit={document['exit_code']}")


def _outcome_class(exit_code: int, observations: list[StageObservation]) -> str:
    if exit_code == 0:
        return "succeeded"
    if any(isinstance(observation, StageLaunchFailed) for observation in observations):
        return "internal_failure"
    return "validation_failed"


def main(argv: list[str]) -> int:
    options = parse_validator_options(argv)
    if options is None:
        return render_usage_error(
            "validate_repository",
            (
                "REPOSITORY_VALIDATION_USAGE_ERROR: invalid presentation options; "
                "next: use --format text|json --color auto|always|never --explain --quiet"
            ),
            json_output=requested_json(argv),
        )
    program = validation_program()
    stage_by_label = {
        label: (script, use_python) for label, script, use_python in STAGES
    }
    state = program.start()
    stage_documents: list[dict[str, object]] = []
    observations: list[StageObservation] = []
    while state.next_stage is not None:
        label = state.next_stage
        script, use_python = stage_by_label[label]
        observation = run_stage(stage_command(script, use_python, sys.executable))
        observations.append(observation)
        if options.format == "json":
            stage_documents.append(_stage_document(label, observation))
        else:
            _render_text_stage(label, observation, options)
        state = program.advance(state, observation)
    exit_code = 0 if state.exit_code is None else state.exit_code
    if options.format == "json":
        print(
            canonical_json(
                {
                    "schema_version": 1,
                    "command": "validate_repository",
                    "outcome_class": _outcome_class(exit_code, observations),
                    "exit_code": exit_code,
                    "stages": stage_documents,
                    "explain": options.explain,
                }
            ).decode("utf-8")
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
