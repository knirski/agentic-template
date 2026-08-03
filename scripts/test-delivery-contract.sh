#!/usr/bin/env bash
set -euo pipefail

review_skill=.agents/skills/pr-review-loop/SKILL.md
release_config=.releaserc
release_workflow=.github/workflows/semantic-release.yml

test -f "$release_config" || {
  echo 'template must include semantic-release configuration' >&2
  exit 1
}

test -f "$release_workflow" || {
  echo 'template must include the semantic-release workflow' >&2
  exit 1
}

python3 - "$release_config" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as config_file:
    config = json.load(config_file)

expected_plugins = [
    "@semantic-release/commit-analyzer",
    "@semantic-release/release-notes-generator",
    "@semantic-release/github",
]

if config.get("branches") != ["main"]:
    raise SystemExit("semantic-release must publish from main")

plugin_names = []
for plugin in config.get("plugins", []):
    if isinstance(plugin, str):
        plugin_names.append(plugin)
    elif isinstance(plugin, list) and plugin and isinstance(plugin[0], str):
        plugin_names.append(plugin[0])
    else:
        raise SystemExit("semantic-release plugins must use string or [name, options] form")

try:
    required_positions = [plugin_names.index(plugin) for plugin in expected_plugins]
except ValueError as error:
    raise SystemExit(
        "semantic-release must analyze commits, generate notes, and publish to GitHub"
    ) from error

if required_positions != sorted(required_positions):
    raise SystemExit("semantic-release core plugins must retain release order")
PY

python3 - .github/workflows/ci.yml "$release_workflow" <<'PY'
import sys


def meaningful_lines(path):
    with open(path, encoding="utf-8") as workflow_file:
        return [
            line.rstrip()
            for line in workflow_file
            if line.strip() and not line.lstrip().startswith("#")
        ]


def nested_block(lines, header, indent):
    marker = f"{' ' * indent}{header}"
    try:
        start = lines.index(marker)
    except ValueError as error:
        raise SystemExit(f"workflow is missing {marker!r}") from error

    block = []
    for line in lines[start + 1 :]:
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= indent:
            break
        block.append(line)
    return block


def require(block, expected):
    if expected not in block:
        raise SystemExit(f"workflow block is missing {expected!r}")


def dependency_names(job_block):
    scalar_prefix = "    needs: "
    scalar_needs = [line for line in job_block if line.startswith(scalar_prefix)]
    if scalar_needs:
        return [scalar_needs[0][len(scalar_prefix) :]]

    needs_block = nested_block(job_block, "needs:", 4)
    return [line.removeprefix("      - ") for line in needs_block if line.startswith("      - ")]


ci_lines = meaningful_lines(sys.argv[1])
ci_events = nested_block(ci_lines, "on:", 0)
require(ci_events, "  workflow_dispatch:")
require(ci_events, "  pull_request:")
ci_push = nested_block(ci_events, "push:", 2)
ci_push_branches = nested_block(ci_push, "branches:", 4)
if ci_push_branches != ["      - main"]:
    raise SystemExit("CI push trigger must target only main")

ci_jobs = nested_block(ci_lines, "jobs:", 0)
delivery_contract = nested_block(ci_jobs, "delivery-contract:", 2)
delivery_steps = nested_block(delivery_contract, "steps:", 4)
delivery_checkout = nested_block(delivery_steps, "- name: Check out repository", 6)
require(delivery_checkout, "        uses: actions/checkout@v6.0.2")
release_call = nested_block(ci_jobs, "release:", 2)
if "delivery-contract" not in dependency_names(release_call):
    raise SystemExit("release job must depend on delivery-contract")
for expected_line in (
    "    if: github.ref == 'refs/heads/main' && (github.event_name == 'push' || github.event_name == 'workflow_dispatch')",
    "    uses: ./.github/workflows/semantic-release.yml",
):
    require(release_call, expected_line)
release_permissions = nested_block(release_call, "permissions:", 4)
for expected_line in (
    "      contents: write",
    "      pull-requests: write",
    "      issues: write",
):
    require(release_permissions, expected_line)

release_lines = meaningful_lines(sys.argv[2])
release_events = nested_block(release_lines, "on:", 0)
if release_events != ["  workflow_call:"]:
    raise SystemExit("semantic-release workflow must only be reusable through workflow_call")

release_concurrency = nested_block(release_lines, "concurrency:", 0)
require(release_concurrency, "  group: semantic-release-${{ github.repository }}")
require(release_concurrency, "  cancel-in-progress: false")

release_jobs = nested_block(release_lines, "jobs:", 0)
release_job = nested_block(release_jobs, "release:", 2)
require(release_job, "    timeout-minutes: 10")
release_steps = nested_block(release_job, "steps:", 4)

release_checkout = nested_block(release_steps, "- name: Check out repository", 6)
for expected_line in (
    "        uses: actions/checkout@v6.0.2",
    "          ref: ${{ github.sha }}",
    "          fetch-depth: 0",
    "          persist-credentials: false",
):
    require(release_checkout, expected_line)

release_eligibility = nested_block(release_steps, "- name: Check release eligibility", 6)
for expected_line in (
    "        id: release-eligibility",
    "          GH_TOKEN: ${{ github.token }}",
    '          main_sha=$(gh api "repos/${GITHUB_REPOSITORY}/git/ref/heads/main" --jq \'.object.sha\')',
    '          if [ "$GITHUB_SHA" = "$main_sha" ]; then',
    '            echo "eligible=true" >> "$GITHUB_OUTPUT"',
):
    require(release_eligibility, expected_line)

release_publish = nested_block(release_steps, "- name: Publish semantic release", 6)
for expected_line in (
    "        if: steps.release-eligibility.outputs.eligible == 'true'",
    "        uses: cycjimmy/semantic-release-action@v6.0.0",
    "          semantic_version: 25.0.8",
    "          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}",
):
    require(release_publish, expected_line)
PY

if grep -Eq 'known bot accounts' "$review_skill"; then
  echo 'pr-review-loop must retain actionable automated-review feedback' >&2
  exit 1
fi

# shellcheck disable=SC2016 # Backticks are literal skill text, not shell substitutions.
if ! grep -Eq 'Invoke `loop-on-ci` immediately after each push' "$review_skill"; then
  echo 'pr-review-loop must return every pushed review fix to the CI gate' >&2
  exit 1
fi
