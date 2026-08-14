"""Bounded subprocess launch and completion effects for the bootstrap shell."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from scripts.bootstrap.errors import ProcessError, SignalNumber, sanitize_process_error
from scripts.bootstrap.result import Err, Ok


@dataclass(frozen=True, slots=True)
class Launched:
    """One completed subprocess: raw returncode and captured streams."""

    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True, slots=True)
class LaunchFailed:
    """The executable could not be launched; ``filename`` is the failed path."""

    process_error: ProcessError
    filename: str | bytes | None = None


@dataclass(frozen=True, slots=True)
class TimedOut:
    """The subprocess exceeded its bounded timeout."""


type ProcessOutcome = Launched | LaunchFailed | TimedOut


def run_captured(
    command: list[str] | tuple[str, ...],
    *,
    cwd: str | bytes | None = None,
    env: dict[str, str] | None = None,
    timeout: float,
    stream_bound: int | None = None,
) -> ProcessOutcome:
    """Run one bounded subprocess; launch and timeout failures are typed values.

    ``stream_bound`` truncates both captured streams after completion.
    """

    try:
        process = subprocess.run(
            list(command),
            cwd=cwd,
            env=env,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except OSError as error:
        return LaunchFailed(
            sanitize_process_error(error),
            # typeshed types OSError.filename as Any; the frozen field narrows it
            filename=error.filename,  # pyright: ignore[reportAny]  deliberate typeshed-boundary narrowing
        )
    except subprocess.TimeoutExpired:
        return TimedOut()
    stdout = process.stdout
    stderr = process.stderr
    if stream_bound is not None:
        stdout = stdout[:stream_bound]
        stderr = stderr[:stream_bound]
    return Launched(returncode=process.returncode, stdout=stdout, stderr=stderr)


def signalled(returncode: int) -> SignalNumber | None:
    """Return the signal a negative returncode encodes, else ``None``."""

    if returncode >= 0:
        return None
    match SignalNumber.from_int(-returncode):
        case Ok(signal):
            return signal
        case Err(_):
            return None
