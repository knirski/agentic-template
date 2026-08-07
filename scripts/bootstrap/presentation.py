"""Deterministic text and canonical JSON presenters for shared validator values."""

from __future__ import annotations

import json

from scripts.bootstrap.canonical_json import canonical_json


def render_json(value: object) -> str:
    return canonical_json(value).decode("utf-8")


def render_text(value: object) -> str:
    if isinstance(value, dict):
        findings = value.get("findings", ())
        lines = [
            f"{item.get('code')}: {item.get('subject')}"
            for item in findings
            if isinstance(item, dict)
        ]
        if lines:
            return "\n".join(lines)
        command = value.get("command")
        return str(command) if command is not None else ""
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
