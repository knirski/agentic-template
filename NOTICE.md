# Bundled Skill Provenance

This template vendors reusable agent skills so generated projects are self-contained.

- Atelier workflow, code-delivery, domain, and debugging skills originate from
  [`martinffx/atelier`](https://github.com/martinffx/atelier).
- `loop-on-ci` originates from [`cursor/plugins`](https://github.com/cursor/plugins).
- `pr-review-loop` originates from
  [`xpepper/pr-review-agent-skill`](https://github.com/xpepper/pr-review-agent-skill) and retains
  its MIT license metadata. This template adds automated-review retention and a mandatory return to
  the CI gate after every pushed review fix.
- `verification-before-completion` originates from
  [`obra/superpowers`](https://github.com/obra/superpowers).
- The Python skills (`python-architecture`, `python-build-tools`, `python-fastapi`,
  `python-modern-python`, `python-monorepo`, `python-sqlalchemy`, `python-temporal`,
  `python-testing`) originate from
  [`martinffx/python-skills`](https://github.com/martinffx/python-skills) and are distributed under
  MIT terms. `python-architecture` and `python-testing` are vendored manually because their upstream
  frontmatter is malformed and the `skills` CLI skips them; the only local change is quoting the
  `description` value so the YAML is valid. `python-modern-python` carries one local correction: its
  pattern-matching example used `case (x, x)`, which is a Python `SyntaxError` (a name bound twice in
  one pattern), replaced with the guarded `case (x, y) if x == y`. Both patches should be reported
  upstream to `martinffx/python-skills`. Reinstall those two through the CLI once the upstream
  frontmatter is fixed, then let `skills-lock.json` manage them.

All bundled skill sources above are distributed under MIT terms. Their copyright and licence notices
must remain available when the bundled skills are redistributed.
Adopter additions to this notice are preserved as seed-once project-owned content.

Review upstream repositories for their current licenses and notices before redistributing this
template outside the permissions granted by those projects.
