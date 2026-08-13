# Licensing and provenance audit

**Audit date:** 2026-08-13
**Scope:** every bundled skill in `.agents/skills`, the repository Apache-2.0 license and notice,
and all bootstrap licensing modes in the approved deterministic-project-bootstrap design.
**Purpose:** establish preservation requirements before licence-writing implementation. This is a
provenance record, not legal advice or a certification that a downstream project is legally valid.

## Evidence and method

The audit compared the local bundled-skill inventory with its recorded upstream source and checked
the upstream repository licence/notice pages available on the audit date. The local files are the
redistributed artefacts; future additions or updates require rerunning this audit for the changed
source. The source links are retained so a maintainer can inspect the exact upstream terms before
publication.

## Bundled skill inventory

All 25 local `SKILL.md` files are covered:

| Local skills | Upstream source | Licence and preservation result |
| --- | --- | --- |
| `atelier-orchestrator`, `atelier-setup`, `code-commit`, `code-handoff`, `code-pull-request`, `code-review`, `code-subagents`, `oracle-debug`, `oracle-domain-modelling`, `oracle-grill-me`, `spec-brainstorm`, `spec-finish`, `spec-implement`, `spec-plan` | [martinffx/atelier](https://github.com/martinffx/atelier) | MIT; retain copyright and licence notice |
| `loop-on-ci` | [cursor/plugins](https://github.com/cursor/plugins) | MIT; retain upstream attribution and licence reference |
| `pr-review-loop` | [xpepper/pr-review-agent-skill](https://github.com/xpepper/pr-review-agent-skill) | MIT; retain upstream MIT metadata and attribution |
| `verification-before-completion` | [obra/superpowers](https://github.com/obra/superpowers) / [obra/superpowers-skills](https://github.com/obra/superpowers-skills) | MIT; retain upstream attribution and licence reference |
| `python-architecture`, `python-build-tools`, `python-fastapi`, `python-modern-python`, `python-monorepo`, `python-sqlalchemy`, `python-temporal`, `python-testing` | [martinffx/python-skills](https://github.com/martinffx/python-skills) | MIT; retain copyright and licence notice. `python-architecture` and `python-testing` are hand-vendored with a quoted `description` because upstream frontmatter is malformed |

The upstream pages identify MIT terms for Atelier, Cursor plugins, xpepper's skill repository,
Superpowers, and martinffx/python-skills. With `modern-python` (Trail of Bits, CC BY-SA 4.0) removed,
every bundled skill is now MIT-licensed.

## Existing notice and required preservation

The root `LICENSE` remains the Apache License 2.0 for original template material. `NOTICE.md` is
the provenance notice for bundled skills and must remain available in every generated-project mode.
It must contain the source repository and attribution for each skill family, the applicable MIT
licence reference, an indication that bundled copies may be adapted locally, and a
direction to review upstream terms before redistributing an updated copy.

This audit adds no new generated path. The existing `LICENSES/Apache-2.0.txt` location remains the
preserved copy of the template Apache text when the adopter supplies a different project licence.
With `modern-python` removed, no bundled skill is CC BY-SA 4.0, so none requires a separate generated
root licence path; every bundled skill's attribution and licence reference remain in `NOTICE.md`. If
a future audit finds that a newly added source requires verbatim licence text or a separate file, that
is a design change requiring reconfirmation before implementation.

Adopter additions to `NOTICE.md` are seed-once content. Bootstrap may initialize the file and may
verify its declared input identity during installation, but Copier and bootstrap reconciliation do
not rewrite it. The root `LICENSE`, `NOTICE.md`, and any generated `LICENSES/*` provenance copies
are seed-once adopter output, never bootstrap-managed output.

## Bootstrap licensing modes

The design defines exactly three explicit modes. There is no default and no `scaffold` mode for
licensing:

| Mode | Root `LICENSE` | Preserved template/provenance material | Input and ownership rule |
| --- | --- | --- | --- |
| `retain-apache-2.0` | The template Apache-2.0 text | `NOTICE.md` remains present | No adopter licence bytes; root licence is seed-once output |
| `provided-project-license` | The adopter-supplied bytes | `NOTICE.md` and `LICENSES/Apache-2.0.txt` | Bytes are required, hashed in `answers.licensing.content_sha256`, and then owned by the adopter |
| `private` | The adopter-supplied private-project terms | `NOTICE.md` and `LICENSES/Apache-2.0.txt` | Bytes are required and hashed; bootstrap does not interpret or certify their legal effect |

For the two supplied-text modes, the input bundle carries exact bytes while the manifest records
only the content digest. Legal prose and secrets are never copied into manifest JSON. In every
mode, bundled-skill provenance remains available through `NOTICE.md`; changing the root project
licence does not remove or relicense the bundled skills.

## Findings and gate decision

- The proposed ownership layout is compatible with the audited licences.
- `NOTICE.md` and this audit are updated for the replacement of `modern-python` (Trail of Bits,
  CC BY-SA 4.0) with the MIT-licensed `martinffx/python-skills` skills; no bundled skill is now
  CC BY-SA 4.0.
- No audited source required a verbatim notice file or a new generated path at this audit point.
- Licence writing remains gated on this audit and the ADR being accepted. Future changes to source
  provenance, licence modes, or legal-file paths require a new audit and design reconfirmation.

**Gate status:** accepted for the current layout after the `NOTICE.md` correction; not a legal
opinion.
