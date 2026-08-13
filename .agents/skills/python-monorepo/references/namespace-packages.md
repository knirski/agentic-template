# Native Namespace Packages

PEP 420 namespaces let independent distributions contribute distinct subpackages to a shared import namespace. Omit `__init__.py` only from the shared namespace directory; each owned subpackage remains a regular package.

```text
packages/acme-auth/src/acme/          # no __init__.py
packages/acme-auth/src/acme/auth/__init__.py
packages/acme-api/src/acme/           # no __init__.py
packages/acme-api/src/acme/api/__init__.py
```

```toml
[project]
name = "acme-auth"
version = "0.1.0"
requires-python = ">=3.12"

[build-system]
requires = ["hatchling>=1.27,<2"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/acme"]
```

Distribution names and import names are separate concepts. `acme-auth` importing as `acme.auth` is a project convention, not a guaranteed dash-to-underscore conversion. Namespace packages reduce top-level naming pressure but do not prevent conflicts: each distribution must own a distinct subpackage and consistently use the same namespace mechanism.

For a workspace dependency, add the normal dependency and an explicit source:

```toml
[project]
dependencies = ["acme-auth"]

[tool.uv.sources]
acme-auth = { workspace = true }
```

Build with `uv build --no-sources` and test wheels and sdists in clean environments before publishing. Consider `project.import-names` and `project.import-namespaces` only after verifying selected build-backend support.
