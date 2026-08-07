"""Strict JSON decoding and deterministic serialization for bootstrap inputs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

MAX_SAFE_INTEGER = 2**53


class _ObjectPairs:
    def __init__(self, pairs: list[tuple[str, Any]]) -> None:
        self.pairs = pairs


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _validate(value: object) -> None:
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
        raise ValueError("floats are not part of the bootstrap JSON domain")
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate(item)
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        for key, item in value.items():
            _validate(key)
            _validate(item)
        return
    raise ValueError(f"unsupported JSON value: {type(value).__name__}")


def _materialize(value: object) -> object:
    if isinstance(value, _ObjectPairs):
        result: dict[str, object] = {}
        for key, item in value.pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = _materialize(item)
        return result
    if isinstance(value, list):
        return [_materialize(item) for item in value]
    return value


def decode_json(data: bytes) -> object:
    """Decode a UTF-8 JSON document into the strict bootstrap value domain."""

    try:
        decoded = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_ObjectPairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("invalid strict JSON") from error
    value = _materialize(decoded)
    _validate(value)
    return value


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
