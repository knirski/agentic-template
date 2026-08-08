"""Creation-time snapshot profile expansions."""

from __future__ import annotations

from typing import Final

PROFILE_CAPABILITIES: Final[dict[str, tuple[str, ...]]] = {
    "portable": (),
    "release-automated": ("semantic-release",),
    "nix-enabled": ("nix",),
    "integrated": (
        "semantic-release",
        "nix",
        "cachix-publish",
        "pr-agent-gemini",
    ),
}
