"""Repository-relative path and text normalization primitives."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from scripts.bootstrap.errors import InputError, InputErrorKind
from scripts.bootstrap.result import Err, Ok, Result


@dataclass(frozen=True, slots=True, order=True)
class RepoPath:
    value: str


def path_byte_key(path: RepoPath) -> bytes:
    """The byte-order key every repository-relative ordering uses."""

    return path.value.encode("utf-8")


def sorted_paths(paths: Iterable[RepoPath]) -> tuple[RepoPath, ...]:
    """Sort repository paths by their UTF-8 byte order."""

    return tuple(sorted(paths, key=path_byte_key))


def parse_path(value: str) -> Result[RepoPath, InputError]:
    if not isinstance(value, str) or not value or value.startswith("/"):  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
        return Err(InputError(InputErrorKind.UNSAFE_RELATIVE_PATH, str(value)))
    if "\\" in value or any(
        ord(char) < 0x20 or 0xD800 <= ord(char) <= 0xDFFF for char in value
    ):
        return Err(InputError(InputErrorKind.UNSAFE_RELATIVE_PATH, value))
    components = value.split("/")
    if any(component in {"", ".", ".."} for component in components):
        return Err(InputError(InputErrorKind.UNSAFE_RELATIVE_PATH, value))
    return Ok(RepoPath(value))


def normalize_text(data: bytes) -> bytes:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("text artifact is not valid UTF-8") from error
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return (text.rstrip("\n") + "\n").encode("utf-8")
