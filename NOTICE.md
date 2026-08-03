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

Review upstream repositories for their current licenses and notices before redistributing this
template outside the permissions granted by those projects.
