#!/usr/bin/env bash
set -euo pipefail

review_skill=.agents/skills/pr-review-loop/SKILL.md
release_config=.releaserc
release_workflow=.github/workflows/semantic-release.yml
pr_agent_config=.pr_agent.toml
pr_agent_workflow=.github/workflows/pr-agent.yml

test -f "$release_config" || {
  echo 'template must include semantic-release configuration' >&2
  exit 1
}

test -f "$release_workflow" || {
  echo 'template must include the semantic-release workflow' >&2
  exit 1
}

test -f "$pr_agent_config" || {
  echo 'template must include PR Agent configuration' >&2
  exit 1
}

test -f "$pr_agent_workflow" || {
  echo 'template must include the PR Agent workflow' >&2
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

python3 - "$pr_agent_config" <<'PY'
import sys

if sys.version_info < (3, 11):
    raise SystemExit("PR Agent configuration validation requires Python 3.11 or newer")

import tomllib

with open(sys.argv[1], "rb") as config_file:
    config = tomllib.load(config_file)

agent_config = config.get("config", {})
if agent_config.get("model") != "gemini/gemini-3.6-flash":
    raise SystemExit("PR Agent must use the Gemini 3.6 Flash model")
if agent_config.get("fallback_models") != ["gemini/gemini-3.5-flash-lite"]:
    raise SystemExit("PR Agent must retain the Gemini Flash Lite fallback")

action_config = config.get("github_action_config", {})
for setting in ("auto_review", "auto_describe", "auto_improve"):
    if action_config.get(setting) is not True:
        raise SystemExit(f"PR Agent must enable {setting}")
if "verbose" in action_config:
    raise SystemExit("PR Agent configuration must not use the unsupported verbose setting")
if action_config.get("pr_actions") != ["opened", "reopened", "ready_for_review"]:
    raise SystemExit("PR Agent must run automatically for the supported PR actions")

suggestions = config.get("pr_code_suggestions", {})
if suggestions.get("commitable_code_suggestions") is not True:
    raise SystemExit("PR Agent must publish committable code suggestions")
if suggestions.get("dual_publishing_score_threshold") != 5:
    raise SystemExit("PR Agent must retain the code-suggestion score threshold")
PY

python3 - .github/workflows/ci.yml "$release_workflow" "$pr_agent_workflow" <<'PY'
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

pr_agent_lines = meaningful_lines(sys.argv[3])
pr_agent_events = nested_block(pr_agent_lines, "on:", 0)
pr_events = nested_block(pr_agent_events, "pull_request:", 2)
if nested_block(pr_events, "types:", 4) != [
    "      - opened",
    "      - reopened",
    "      - ready_for_review",
]:
    raise SystemExit("PR Agent must run for the supported pull request actions")
comment_events = nested_block(pr_agent_events, "issue_comment:", 2)
if nested_block(comment_events, "types:", 4) != ["      - created"]:
    raise SystemExit("PR Agent must accept commands from new PR comments")

if "permissions: {}" not in pr_agent_lines:
    raise SystemExit("PR Agent workflow must deny permissions by default")

pr_agent_concurrency = nested_block(pr_agent_lines, "concurrency:", 0)
for expected_line in (
    "  group: pr-agent-${{ github.event_name }}-${{ github.event.pull_request.number || github.event.issue.number || github.run_id }}",
    "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}",
):
    require(pr_agent_concurrency, expected_line)

pr_agent_jobs = nested_block(pr_agent_lines, "jobs:", 0)
pr_agent_job = nested_block(pr_agent_jobs, "pr-agent:", 2)
for expected_line in (
    "      (github.event_name == 'pull_request' &&",
    "        github.event.pull_request.head.repo.full_name == github.repository &&",
    "        github.event.sender.type != 'Bot') ||",
    "      (github.event_name == 'issue_comment' &&",
    "        github.event.issue.pull_request != null &&",
    "        github.event.sender.type != 'Bot' &&",
    "        contains(fromJSON('[\"OWNER\", \"MEMBER\", \"COLLABORATOR\"]'), github.event.comment.author_association) &&",
    "        (github.event.comment.body == '/review' ||",
    "          startsWith(github.event.comment.body, '/review ') ||",
    "          github.event.comment.body == '/describe' ||",
    "          startsWith(github.event.comment.body, '/describe ') ||",
    "          github.event.comment.body == '/improve' ||",
    "          startsWith(github.event.comment.body, '/improve ')))",
    "    runs-on: ubuntu-24.04",
    "    timeout-minutes: 10",
):
    require(pr_agent_job, expected_line)

job_permissions = nested_block(pr_agent_job, "permissions:", 4)
expected_job_permissions = [
    "      contents: read",
    "      issues: write",
    "      pull-requests: write",
]
if job_permissions != expected_job_permissions:
    raise SystemExit("PR Agent job permissions must match the exact approved set")

pr_agent_steps = nested_block(pr_agent_job, "steps:", 4)
if any("actions/checkout@" in line for line in pr_agent_steps):
    raise SystemExit("PR Agent must not check out pull request contents")

secret_check = nested_block(pr_agent_steps, "- name: Validate Gemini API key secret", 6)
for expected_line in (
    "          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}",
    '          if [ -z "$GEMINI_API_KEY" ]; then',
):
    require(secret_check, expected_line)

agent_step = nested_block(pr_agent_steps, "- name: Run PR Agent", 6)
for expected_line in (
    "        uses: the-pr-agent/pr-agent@v0.40.0",
    "          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}",
    "          GOOGLE_AI_STUDIO.GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}",
):
    require(agent_step, expected_line)
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
