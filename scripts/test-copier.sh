#!/usr/bin/env bash
set -euo pipefail

if command -v copier >/dev/null; then
  copier_command=(copier)
elif command -v uvx >/dev/null; then
  copier_command=(uvx --from copier copier)
else
  echo "Copier is required; install it with: uv tool install copier" >&2
  exit 1
fi

repository=$(pwd)
workspace=$(mktemp -d "${TMPDIR:-/tmp}/agentic-template-copier.XXXXXX")
trap 'rm -rf "$workspace"' EXIT

source="$workspace/source"
project="$workspace/project"
mkdir -p "$source"

while IFS= read -r path; do
  test -e "$repository/$path" || continue
  mkdir -p "$source/$(dirname "$path")"
  cp "$repository/$path" "$source/$path"
done < <(git ls-files --cached --others --exclude-standard)

git -C "$source" init --initial-branch=main >/dev/null
git -C "$source" config user.email test@example.invalid
git -C "$source" config user.name "Copier Test"
git -C "$source" add .
git -C "$source" commit -m "template v0.1.0" >/dev/null
git -C "$source" tag v0.1.0

"${copier_command[@]}" copy "$source" "$project" --vcs-ref v0.1.0
test -f "$project/.copier-answers.yml"
test -f "$project/README.md"
test -f "$project/copier.yml"
test ! -e "$project/template-manifest.json"
test ! -e "$project/TEMPLATE_VERSION"
test ! -e "$project/tools"
test ! -e "$project/.github/workflows/copier-smoke.yml"
test ! -e "$project/scripts/test-copier.sh"
(cd "$project" && bash scripts/validate-template.sh)

git -C "$source" config user.email test@example.invalid
printf '\nCopier smoke-test marker.\n' >> "$source/NOTICE.md"
git -C "$source" add NOTICE.md
git -C "$source" commit -m "template v0.2.0" >/dev/null
git -C "$source" tag v0.2.0

git -C "$project" init --initial-branch=main >/dev/null
git -C "$project" config user.email test@example.invalid
git -C "$project" config user.name "Copier Test"
git -C "$project" add .
git -C "$project" commit -m "generated project" >/dev/null

(cd "$project" && "${copier_command[@]}" update --vcs-ref v0.2.0)
grep -q 'Copier smoke-test marker.' "$project/NOTICE.md"
