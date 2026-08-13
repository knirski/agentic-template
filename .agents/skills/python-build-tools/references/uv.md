# uv Projects

Use uv for project dependency resolution, environments, and package builds. It supports many pip workflows but is not a drop-in implementation of every pip command or option. See the [official documentation](https://docs.astral.sh/uv/).

## Dependencies and locks

Use PEP 735 dependency groups for local development tools. Use optional dependencies only for features users can request when installing a published package.

```toml
[project]
name = "my-project"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["fastapi>=0.100,<1"]

[dependency-groups]
dev = ["pytest", "ruff", "basedpyright"]
```

```bash
uv add fastapi
uv add --dev pytest ruff basedpyright
uv lock --upgrade-package fastapi
uv sync --locked
uv run --locked pytest
uv export --format requirements.txt -o requirements.txt
```

Commit `uv.lock`. In CI, `uv sync --locked` verifies that the lock matches project metadata. Use `--frozen` only when intentionally skipping that check.

## Workspaces

Workspace configuration belongs in the root project. A member dependency needs both the normal dependency declaration and an explicit uv source.

```toml
[tool.uv.workspace]
members = ["packages/*"]
exclude = ["packages/experimental"]

[tool.uv.sources]
my-core = { workspace = true }
```

Use `uv sync --package my-api` for one member or `uv sync --all-packages` when a command needs all members. Read `python-monorepo` for layout and Docker guidance.

## Builds and publishing

```bash
uv build --no-sources
uv publish
```

`--no-sources` verifies that distributions do not accidentally depend on development-only `tool.uv.sources`. Test both the wheel and sdist in clean environments before publishing. Prefer Trusted Publishing/OIDC in CI instead of long-lived upload tokens.

## Indexes and secrets

Use named, explicit indexes when a package must come from a private or TestPyPI index. Do not put credentials in `pyproject.toml` or `uv.lock`.

```toml
[[tool.uv.index]]
name = "testpypi"
url = "https://test.pypi.org/simple/"
publish-url = "https://test.pypi.org/legacy/"
explicit = true
```

Never commit `.env`. Add it to `.gitignore`, commit an `.env.example` containing only placeholders, and inject production secrets from a managed secret store or CI secret mechanism.

## Troubleshooting

```bash
uv cache clean
uv python list
uv tree
uv lock --check
```

`uv self update` works only for standalone uv installations. Upgrade uv through Homebrew, pipx, or another package manager when that installed it.
