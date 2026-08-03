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

if grep -Eq 'known bot accounts' "$review_skill"; then
  echo 'pr-review-loop must retain actionable automated-review feedback' >&2
  exit 1
fi

# shellcheck disable=SC2016 # Backticks are literal skill text, not shell substitutions.
if ! grep -Eq 'Invoke `loop-on-ci` immediately after each push' "$review_skill"; then
  echo 'pr-review-loop must return every pushed review fix to the CI gate' >&2
  exit 1
fi
