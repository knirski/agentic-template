#!/usr/bin/env bash
set -euo pipefail

if grep -En '(^|[[:space:]])rg([[:space:]]|$)' scripts/*.sh; then
  echo 'template validation must not require ripgrep on GitHub-hosted runners' >&2
  exit 1
fi
