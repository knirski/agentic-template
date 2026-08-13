"""Deterministic text and canonical JSON presenters for shared validator values."""

from __future__ import annotations

import json
from typing import cast

from scripts.bootstrap.canonical_json import canonical_json


def render_json(value: object) -> str:
    return canonical_json(value).decode("utf-8")


def render_text(value: object) -> str:
    if isinstance(value, dict):
        mapping = cast(dict[str, object], value)
        raw_findings = mapping.get("findings", ())
        if isinstance(raw_findings, (list, tuple)):
            lines: list[str] = []
            for item in cast(list[object] | tuple[object, ...], raw_findings):
                if not isinstance(item, dict):
                    continue
                entry = cast(dict[str, object], item)
                code = entry.get("code")
                subject = entry.get("subject")
                if "message" in entry and "next_action" in entry:
                    lines.append(
                        f"{code}: {subject}: {entry.get('message')}; next: {entry.get('next_action')}"
                    )
                else:
                    lines.append(f"{code}: {subject}")
            if lines:
                return "\n".join(lines)
        command = mapping.get("command")
        return str(command) if command is not None else ""
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
