#!/usr/bin/env bash
set -euo pipefail

required_files=(
  AGENTS.md
  README.md
  docs/prd.md
  docs/agents/domain.md
  docs/agents/issue-tracker.md
  .github/ISSUE_TEMPLATE/bug.yml
  .github/ISSUE_TEMPLATE/feature.yml
  .github/pull_request_template.md
  .github/workflows/ci.yml
)

required_skills=(
  atelier-orchestrator
  code-commit
  code-pull-request
  code-review
  loop-on-ci
  pr-review-loop
  verification-before-completion
)

for path in "${required_files[@]}"; do
  test -f "$path" || { echo "missing required file: $path" >&2; exit 1; }
done

for skill in "${required_skills[@]}"; do
  skill_file=".agents/skills/$skill/SKILL.md"
  test -f "$skill_file" || { echo "missing required skill: $skill" >&2; exit 1; }
done

while IFS= read -r skill_file; do
  test "$(sed -n '1p' "$skill_file")" = '---' || {
    echo "missing frontmatter delimiter: $skill_file" >&2
    exit 1
  }
  sed -n '2,/^---$/p' "$skill_file" | grep -Eq '^name:' || {
    echo "missing skill name: $skill_file" >&2
    exit 1
  }
  sed -n '2,/^---$/p' "$skill_file" | grep -Eq '^description:' || {
    echo "missing skill description: $skill_file" >&2
    exit 1
  }
done < <(find .agents/skills -name SKILL.md -type f | sort)

scripts/test-portable-validation.sh
scripts/test-delivery-contract.sh
git diff --check
