"""Pure input-boundary decoding for bootstrap answer bundles."""

from __future__ import annotations

from collections.abc import Mapping

from scripts.bootstrap.schemas import BootstrapBundle


def decode_bundle(value: Mapping[str, object]) -> BootstrapBundle:
    """Decode a primitive mapping without reading or executing referenced content."""

    return BootstrapBundle.model_validate(value)
