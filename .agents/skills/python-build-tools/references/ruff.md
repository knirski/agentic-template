# Ruff

Ruff provides linting and formatting. It can replace many Black, isort, and Flake8 workflows, but rule coverage differs from Pylint and other linters. See the [official documentation](https://docs.astral.sh/ruff/).

## Configuration

```toml
[tool.ruff]
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "C4", "SIM", "RUF", "PT"]
ignore = ["E501"]

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]

[tool.ruff.format]
quote-style = "double"
docstring-code-format = true
```

Do not select `Q` quote rules while Ruff formats code; the formatter owns quote style. Do not ignore removed rule `PT004`. `E203` is a preview rule and does not need an ignore in this stable configuration.

## Commands

```bash
# Verify; use in CI.
ruff check .
ruff format --check .

# Repair locally; format after lint fixes.
ruff check --fix .
ruff format .

# Inspect instead of changing files.
ruff check --diff .
ruff clean
```

`list(map(...))` is reported by `C417`, not `C401`.

## Pre-commit

Pin the Ruff release deliberately and use the current hook identifiers:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v<reviewed-ruff-release>
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format
```

Run the non-mutating commands above in CI even when pre-commit applies fixes locally.
