"""Secret preflight structural policy and the local non-secret canary.

The design pins the preflight as a fixed trusted job: no checkout, no ``uses:``
at all, no repository content or script execution, no untrusted expression
interpolation, no shell tracing, the secret referenced exactly once and never
printed or written, and only a literal ``available`` boolean plus constant
guidance as outputs.  The canary runs the preflight script outside GitHub with
a non-secret sentinel and asserts the sentinel appears in no stdout, stderr,
step output, or written file -- log masking inside Actions makes log absence
there near-vacuous evidence.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.fixtures import render_for

# (workflow path, preflight job, privileged job, secret name)
PREFLIGHT_WORKFLOWS: tuple[tuple[str, str, str, str], ...] = (
    (
        ".github/workflows/pr-agent.yml",
        "gemini-availability",
        "pr-agent",
        "GEMINI_API_KEY",
    ),
    (
        ".github/workflows/pr-agent-commands.yml",
        "gemini-availability",
        "pr-agent",
        "GEMINI_API_KEY",
    ),
    (
        ".github/workflows/cachix-publish.yml",
        "cachix-availability",
        "publish",
        "CACHIX_AUTH_TOKEN",
    ),
)

_TRACING = re.compile(r"set\s+-[a-z]*[xv][a-z]*")
_SENTINEL = "sentinel-do-not-leak-7391"


def _job_block(text: str, job: str) -> str:
    """One job body from its key line through its last line."""
    lines = text.splitlines()
    start = next(index for index, line in enumerate(lines) if line == f"  {job}:")
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            break
        block.append(line)
    return "\n".join(block)


def _preflight_script(workflow: str, preflight_job: str) -> str:
    """The preflight ``run: |`` block verbatim, for the local canary."""
    block = _job_block(workflow, preflight_job).splitlines()
    run_index = next(
        index for index, line in enumerate(block) if line.strip() == "run: |"
    )
    base_indent = len(block[run_index]) - len(block[run_index].lstrip())
    script: list[str] = []
    for line in block[run_index + 1 :]:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if not stripped:
            script.append("")
            continue
        if indent <= base_indent:
            break
        script.append(line[base_indent + 2 :])
    return "\n".join(script)


def _outputs_keys(block: str) -> list[str]:
    """The job's declared output names, in order."""
    body = block.split("outputs:", 1)[-1].split("steps:", 1)[0]
    return [line.split(":", 1)[0].strip() for line in body.splitlines() if line.strip()]


def test_preflight_structural_policy() -> None:
    """The fixed trusted job: no content, no actions, one secret, no tracing."""
    rendered = render_for(("pr-agent-gemini", "nix", "cachix-publish"))
    for path, preflight_job, _privileged, secret in PREFLIGHT_WORKFLOWS:
        text = rendered[path].decode("utf-8")
        block = _job_block(text, preflight_job)
        script = _preflight_script(text, preflight_job)
        assert "uses:" not in block, f"{path}: preflight uses an action"
        assert "checkout" not in block.lower(), f"{path}: preflight checks out"
        assert "./" not in block, f"{path}: preflight runs a repository path"
        assert "scripts/" not in block, f"{path}: preflight runs a repository script"
        assert "${{ github." not in block, f"{path}: preflight inlines event data"
        assert "needs:" not in block, f"{path}: preflight depends on another job"
        assert block.count("${{ secrets.") == 1, (
            f"{path}: preflight must reference the secret exactly once"
        )
        assert f"${{{{ secrets.{secret} }}}}" in block
        assert _TRACING.search(script) is None, f"{path}: preflight traces commands"
        assert _outputs_keys(block) == ["available", "guidance"], (
            f"{path}: preflight outputs are not exactly available and guidance"
        )


@pytest.mark.parametrize(
    ("path", "preflight_job", "privileged_job", "_secret"),
    PREFLIGHT_WORKFLOWS,
)
def test_privileged_jobs_are_blocked_when_preflight_is_unavailable(
    path: str, preflight_job: str, privileged_job: str, _secret: str
) -> None:
    rendered = render_for(("pr-agent-gemini", "nix", "cachix-publish"))
    text = rendered[path].decode("utf-8")
    block = _job_block(text, privileged_job)
    assert f"needs: [{preflight_job}]" in block
    assert f"needs.{preflight_job}.outputs.available == 'true'" in block
    assert "always()" not in block
    assert "continue-on-error" not in block


def test_cachix_publish_job_is_gated_on_default_branch_and_nix_check() -> None:
    rendered = render_for(("nix", "cachix-publish"))
    ci = rendered[".github/workflows/ci.yml"].decode("utf-8")
    block = _job_block(ci, "cachix-publish")
    assert "needs: [nix-check]" in block
    assert "github.ref_name == github.event.repository.default_branch" in block
    assert "github.event_name == 'push'" in block
    assert "workflow_dispatch" in block
    assert "always()" not in block


def test_cachix_unavailable_skips_publish_without_failing() -> None:
    """An unavailable token must skip publishing, not fail Nix validation."""
    rendered = render_for(("nix", "cachix-publish"))
    text = rendered[".github/workflows/cachix-publish.yml"].decode("utf-8")
    publish = _job_block(text, "publish")
    assert "needs.cachix-availability.outputs.available == 'true'" in publish
    assert "continue-on-error" not in publish
    assert "always()" not in publish


def test_invalid_cache_fails_as_an_activation_error() -> None:
    """An invalid configured cache fails the publish job rather than being ignored."""
    rendered = render_for(("nix", "cachix-publish"))
    text = rendered[".github/workflows/cachix-publish.yml"].decode("utf-8")
    publish = _job_block(text, "publish")
    assert "cachix/cachix-action" in publish
    assert "authToken: ${{ secrets.CACHIX_AUTH_TOKEN }}" in publish
    # No tolerance: a failing cachix-action aborts the job.
    assert "continue-on-error" not in publish
    assert "if: always()" not in publish


@pytest.mark.parametrize(
    ("path", "preflight_job", "_privileged_job", "secret"),
    PREFLIGHT_WORKFLOWS,
)
def test_local_canary_never_leaks_the_sentinel(
    path: str, preflight_job: str, _privileged_job: str, secret: str
) -> None:
    """Every preflight script run outside GitHub leaks no secret value anywhere."""
    rendered = render_for(("pr-agent-gemini", "nix", "cachix-publish"))
    script = _preflight_script(rendered[path].decode("utf-8"), preflight_job)
    with tempfile.TemporaryDirectory(prefix="agentic-template-canary.") as raw:
        directory = Path(raw)
        output = directory / "github-output"
        env = {
            **{key: value for key, value in os.environ.items() if key != secret},
            secret: _SENTINEL,
            "GITHUB_OUTPUT": str(output),
        }
        available = subprocess.run(
            ["sh", "-c", script],
            cwd=directory,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        output_text = output.read_text(encoding="utf-8")
        written = sorted(path.name for path in directory.iterdir())
    assert available.returncode == 0, available.stderr
    leaked = [
        stream
        for stream, content in (
            ("stdout", available.stdout),
            ("stderr", available.stderr),
            ("output", output_text),
        )
        if _SENTINEL in content
    ]
    assert leaked == [], f"sentinel leaked through: {leaked}"
    assert "available=true" in output_text
    assert "guidance=" in output_text
    assert written == ["github-output"]


@pytest.mark.parametrize(
    ("path", "preflight_job", "_privileged_job", "secret"),
    PREFLIGHT_WORKFLOWS,
)
def test_canary_unavailable_state_is_constant_guidance(
    path: str, preflight_job: str, _privileged_job: str, secret: str
) -> None:
    rendered = render_for(("pr-agent-gemini", "nix", "cachix-publish"))
    script = _preflight_script(rendered[path].decode("utf-8"), preflight_job)
    with tempfile.TemporaryDirectory(prefix="agentic-template-canary.") as raw:
        directory = Path(raw)
        output = directory / "github-output"
        env = {
            **{key: value for key, value in os.environ.items() if key != secret},
            "GITHUB_OUTPUT": str(output),
        }
        unavailable = subprocess.run(
            ["sh", "-c", script],
            cwd=directory,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        content = output.read_text(encoding="utf-8")
    assert unavailable.returncode == 0, unavailable.stderr
    assert "available=false" in content
    assert "docs/github-setup.md" in content
    assert "available=true" not in content


def test_privileged_jobs_check_out_the_repository() -> None:
    """Nix and Cachix jobs build from the repository, not an empty workspace."""
    rendered = render_for(("nix", "cachix-publish"))
    for path, job in (
        (".github/workflows/nix.yml", "nix-check"),
        (".github/workflows/cachix-publish.yml", "publish"),
    ):
        block = _job_block(rendered[path].decode("utf-8"), job)
        assert "actions/checkout" in block, f"{path}: {job} never checks out"
        assert "persist-credentials: false" in block, (
            f"{path}: {job} persists credentials"
        )


def test_cachix_caller_forwards_the_auth_token_secret() -> None:
    """The caller must pass the token into the reusable workflow."""
    rendered = render_for(("nix", "cachix-publish"))
    ci = rendered[".github/workflows/ci.yml"].decode("utf-8")
    block = _job_block(ci, "cachix-publish")
    assert "secrets: inherit" in block


def test_cachix_run_block_never_interpolates_the_cache_name() -> None:
    """The cache name reaches the shell only through an environment variable."""
    rendered = render_for(("nix", "cachix-publish"))
    text = rendered[".github/workflows/cachix-publish.yml"].decode("utf-8")
    publish = _job_block(text, "publish")
    run_block = publish.split("run: |", 1)[-1]
    assert "CACHIX_CACHE_NAME" in run_block
    assert "agentic-template:value:" not in run_block
    assert "cachix push" in run_block
    assert "$CACHIX_CACHE_NAME" in run_block


def test_cachix_preflight_shares_the_fixed_trusted_shape() -> None:
    rendered = render_for(("nix", "cachix-publish"))
    text = rendered[".github/workflows/cachix-publish.yml"].decode("utf-8")
    block = _job_block(text, "cachix-availability")
    assert block.count("${{ secrets.") == 1
    assert "${{ secrets.CACHIX_AUTH_TOKEN }}" in block
    assert "uses:" not in block
    assert "checkout" not in block.lower()
    assert "github." not in block
    assert "guidance=" in block
