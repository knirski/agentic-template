#!/usr/bin/env bash
set -euo pipefail

review_skill=.agents/skills/pr-review-loop/SKILL.md

if rg -q 'known bot accounts' "$review_skill"; then
  echo 'pr-review-loop must retain actionable automated-review feedback' >&2
  exit 1
fi

if ! rg -q 'Invoke `loop-on-ci` immediately after each push' "$review_skill"; then
  echo 'pr-review-loop must return every pushed review fix to the CI gate' >&2
  exit 1
fi
