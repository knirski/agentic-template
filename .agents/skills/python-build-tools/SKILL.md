---
name: python-build-tools
description: Python project tooling with uv, mise, Ruff, basedpyright, and pytest. Use for pyproject.toml, dependency groups, lockfiles, uv sync/run/build/publish, reproducible CI, Ruff, basedpyright, or Python tool-version setup. For uv multi-package layouts and Docker, use python-monorepo.
user-invocable: false
---

# Python Build Tools

Modern Python development tooling using uv, mise, Ruff, basedpyright, and pytest. Target Python 3.12-3.14 and stable tool releases.

## Quick Start

### Minimal pyproject.toml

```toml
[project]
name = "my-project"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["fastapi", "pydantic"]

[dependency-groups]
dev = ["pytest", "pytest-cov", "ruff", "basedpyright"]

[build-system]
requires = ["hatchling>=1.27,<2"]
build-backend = "hatchling.build"

[tool.ruff]
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "RUF"]

[tool.basedpyright]
typeCheckingMode = "strict"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

### Setup Project

```bash
uv init my-project && cd my-project
uv sync
uv add fastapi pydantic
uv add --dev pytest pytest-cov ruff basedpyright
```

## Tool Overview

| Tool | Purpose | Replaces |
|------|---------|----------|
| **uv** | Package and environment management | Many pip and virtualenv workflows |
| **mise** | Version & tasks | pyenv, asdf |
| **ruff** | Lint & format | Many Black, isort, and Flake8 workflows |
| **basedpyright** | Type checking | A stricter pyright-compatible checker |
| **pytest** | Testing | unittest |

## Common Commands

### Lint and Format

```bash
uv run ruff check .
uv run ruff format --check .

# Apply changes locally, never in CI.
uv run ruff check --fix .
uv run ruff format .
```

### Type Check

```bash
uv run basedpyright
uv run basedpyright src/main.py
```

### Test

```bash
uv run pytest
uv run pytest --cov=src --cov-report=html
```

### Manage Dependencies

```bash
uv add fastapi
uv add --dev pytest
uv lock --upgrade
uv tree
```

## Mise Configuration

Create `.mise.toml` for consistent development:

```toml
[tools]
python = "3.14"

[tasks.lint]
run = "uv run ruff check ."

[tasks.format]
run = "uv run ruff format --check ."

[tasks.typecheck]
run = "uv run basedpyright"

[tasks.test]
run = "uv run pytest"

[tasks.check]
depends = ["lint", "format", "typecheck", "test"]
```

Usage:

```bash
mise install
mise run check
```

## Type Hints Example

```python
from decimal import Decimal
from typing import Optional

def calculate_discount(
    total: Decimal,
    rate: Optional[Decimal] = None
) -> Decimal:
    if rate is None:
        rate = Decimal("0.1")
    return total * rate
```

## Best Practices

1. Commit `uv.lock` and use `uv sync --locked` in CI.
2. Pin tool versions in CI or through `tool.uv.required-version`; refresh deliberately.
3. Declare compatible dependency ranges in metadata and use the lockfile for selected versions.
4. Separate non-mutating checks from local auto-fixes.
5. Use optional dependencies only for published user-selectable features, not development tools.

## References

For detailed configuration and advanced patterns:

- **[references/uv.md](references/uv.md)** - Dependency groups, locks, indexes, builds, and publishing
- **[references/ruff.md](references/ruff.md)** - Rules, per-file ignores, pre-commit integration
- **[references/basedpyright.md](references/basedpyright.md)** - Type patterns, generics, protocols
