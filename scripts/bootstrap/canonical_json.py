"""Strict JSON decoding and deterministic serialization for bootstrap inputs."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from typing import cast

from scripts.bootstrap.result import Err, Ok, Result

MAX_SAFE_INTEGER = 2**53
MAX_NESTING_DEPTH = 128


type StrictJsonValue = (
    dict[str, StrictJsonValue] | list[StrictJsonValue] | str | int | float | bool | None
)


class _ObjectPairs:
    pairs: list[tuple[str, object]]

    def __init__(self, pairs: list[tuple[str, object]]) -> None:
        self.pairs = pairs


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _loads(data: str) -> object:
    return cast(
        object,
        json.loads(
            data,
            object_pairs_hook=_ObjectPairs,
            parse_constant=_reject_constant,
        ),
    )


def _validate(value: object, depth: int = 0) -> None:
    if depth > MAX_NESTING_DEPTH:
        raise ValueError("exceeds the maximum JSON nesting depth")
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str) and any(
            0xD800 <= ord(char) <= 0xDFFF for char in value
        ):
            raise ValueError("surrogate code point")
        return
    if isinstance(value, int) and not isinstance(value, bool):
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise ValueError("integer outside safe JSON range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                "non-finite floats are not part of the bootstrap JSON domain"
            )
        return
    if isinstance(value, (list, tuple)):
        items = cast(list[object] | tuple[object, ...], value)
        for item in items:
            _validate(item, depth + 1)
        return
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        if any(not isinstance(key, str) for key in mapping):
            raise ValueError("JSON object keys must be strings")
        for key, item in mapping.items():
            _validate(key, depth + 1)
            _validate(item, depth + 1)
        return
    raise ValueError(f"unsupported JSON value: {type(value).__name__}")


def _materialize(value: object, depth: int = 0) -> object:
    if depth > MAX_NESTING_DEPTH:
        raise ValueError("exceeds the maximum JSON nesting depth")
    if isinstance(value, _ObjectPairs):
        result: dict[str, object] = {}
        for key, item in value.pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = _materialize(item, depth + 1)
        return result
    if isinstance(value, list):
        items = cast(list[object], value)
        return [_materialize(item, depth + 1) for item in items]
    return value


def decode_json(data: bytes) -> StrictJsonValue:
    """Decode a UTF-8 JSON document into the strict bootstrap value domain."""

    try:
        decoded = _loads(data.decode("utf-8"))
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as error:
        raise ValueError("invalid strict JSON") from error
    try:
        value = _materialize(decoded)
    except RecursionError as error:
        raise ValueError("invalid strict JSON") from error
    try:
        _validate(value)
    except RecursionError as error:
        raise ValueError("invalid strict JSON") from error
    return cast(StrictJsonValue, value)


def decode_object[ErrorT](
    data: bytes,
    *,
    error: Callable[[str], ErrorT],
    max_bytes: int | None = None,
    allowed_keys: frozenset[str] | None = None,
) -> Result[dict[str, StrictJsonValue], ErrorT]:
    """Strictly decode one bounded document into a mapping of the closed key set.

    ``error`` receives exactly one of the reasons ``"size"`` (only with
    ``max_bytes``), ``"json"``, or ``"document"`` so callers map the shared
    skeleton onto their own error vocabulary.
    """

    if max_bytes is not None and len(data) > max_bytes:
        return Err(error("size"))
    try:
        value = decode_json(data)
    except ValueError:
        return Err(error("json"))
    if not isinstance(value, dict):
        return Err(error("document"))
    if allowed_keys is not None and set(value) != set(allowed_keys):
        return Err(error("document"))
    return Ok(value)


def canonical_json(value: object) -> bytes:
    """Serialize a strict bootstrap value deterministically as UTF-8 JSON."""

    _validate(value)
    try:
        return json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as error:
        raise ValueError("value cannot be serialized as strict JSON") from error
