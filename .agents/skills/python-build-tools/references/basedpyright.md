# basedpyright

basedpyright is a pyright-compatible type checker with stricter defaults. Consult the [official configuration reference](https://docs.basedpyright.com/latest/configuration/config-files/) for version-specific settings.

## Configuration

Start with the current recommended mode. Use strict mode only after the project can satisfy its stricter diagnostics.

```toml
[tool.basedpyright]
pythonVersion = "3.12"
include = ["src", "tests"]
exclude = [".venv", "build", "dist"]
typeCheckingMode = "recommended"
```

Do not set `typeshedPath` or `stubPath` unless supplying real custom directories. For stricter projects, change only `typeCheckingMode` to `"strict"`; do not duplicate individual diagnostic keys merely to restate a mode.

Modes are `off`, `basic`, `standard`, `strict`, `recommended`, and `all`. The latest stable default is `recommended`.

## Commands and integration

```bash
uv run basedpyright
uv run basedpyright src
uv run basedpyright --verbose
uv run basedpyright --outputjson
```

Install the `detachhead.basedpyright` VS Code extension. Do not enable Pylance type checking at the same time unless following its documented coexistence setup.

For pre-commit, execute the project-pinned binary and the whole project:

```yaml
- repo: local
  hooks:
    - id: basedpyright
      entry: uv run basedpyright
      language: system
      pass_filenames: false
```

## Suppressions and baselines

Fix types rather than suppressing them. If an exception is unavoidable, use a precise basedpyright rule:

```python
value: int = some_string_func()  # pyright: ignore[reportAssignmentType]
```

Do not delete `.basedpyright`: its default location can contain the project baseline. Manage baselines with the documented `--writebaseline`, `--baselinefile`, and baseline modes.

Install third-party stubs as development dependencies when available:

```bash
uv add --dev types-requests types-pyyaml
```
