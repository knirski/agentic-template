"""Pure contribution and document-fragment composition for the render boundary.

Composition resolves contribution bodies and document-fragment bodies from verified blobs,
applies substitutions with the declared context encoder, and returns contributions in the
normative slot order. Every referenced blob must be present before any body is rendered.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from scripts.bootstrap.blobs import VerifiedBlobStore
from scripts.bootstrap.capability_fragments import (
    capability_definitions,
    core_definition,
    template_bodies,
)
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.manifest import SlotContent
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.render import (
    CapabilityDefinition,
    ContributionDefinition,
    CoreDefinition,
    DocumentFragmentDefinition,
    LicensingInfo,
    MaintenanceInfo,
    ManagedRender,
    ProfileInfo,
    ProjectInfo,
    RenderContext,
    RenderError,
    RenderErrorKind,
    RenderInput,
    ResolvedContribution,
    apply_substitutions,
    render_managed,
)
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.schemas import SettingValue

CORE_OWNER = "core"


@dataclass(frozen=True, slots=True)
class _RenderedFragment:
    """One rendered document-fragment body with its normative ordering keys."""

    order: int
    owner_order: int
    owner: str
    fragment_id: str
    document: str
    text: str


def _identity(owner: str, contribution_id: str) -> str:
    return f"{owner}.{contribution_id}"


def _owner_pairs(
    core: CoreDefinition,
    definitions: Mapping[str, CapabilityDefinition],
    effective: tuple[str, ...],
) -> Result[
    tuple[tuple[str, int, tuple[ContributionDefinition, ...]], ...], RenderError
]:
    pairs: list[tuple[str, int, tuple[ContributionDefinition, ...]]] = [
        (CORE_OWNER, -1, core.contributions)
    ]
    for owner_order, capability_id in enumerate(effective):
        if capability_id == CORE_OWNER:
            return Err(
                RenderError(
                    RenderErrorKind.INVALID_TEMPLATE, "reserved_owner", capability_id
                )
            )
        definition = definitions.get(capability_id)
        if definition is None:
            return Err(
                RenderError(
                    RenderErrorKind.INVALID_TEMPLATE,
                    "missing_capability_definition",
                    capability_id,
                )
            )
        pairs.append((capability_id, owner_order, definition.contributions))
    return Ok(tuple(pairs))


def compose_contributions(
    core: CoreDefinition,
    definitions: Mapping[str, CapabilityDefinition],
    effective: tuple[str, ...],
    settings: Mapping[str, Mapping[str, SettingValue]],
    project: ProjectInfo,
    maintenance: MaintenanceInfo,
    blobs: VerifiedBlobStore,
) -> Result[tuple[ResolvedContribution, ...], RenderError]:
    """Compose every effective contribution into the normative sorted order.

    Bodies are validated and ordered first; the composed order then feeds the
    release-graph substitution so a release contribution can name every
    selected capability check without a second pass over the input.
    """
    match _owner_pairs(core, definitions, effective):
        case Err(error):
            return Err(error)
        case Ok(owner_pairs):
            pass
    for owner, _order, contributions in owner_pairs:
        for contribution in contributions:
            if blobs.get(contribution.body_blob) is None:
                return Err(
                    RenderError(
                        RenderErrorKind.MISSING_BLOB,
                        "",
                        _identity(owner, contribution.id),
                    )
                )
    identities: set[tuple[str, str, str]] = set()
    for owner, _order, contributions in owner_pairs:
        for contribution in contributions:
            identity = (contribution.slot, owner, contribution.id)
            if identity in identities:
                return Err(
                    RenderError(
                        RenderErrorKind.INVALID_TEMPLATE,
                        "duplicate_contribution_identity",
                        "/".join(identity),
                    )
                )
            identities.add(identity)
    slots_by_id = {slot.id: slot for slot in core.slots}
    raw: list[tuple[ContributionDefinition, bytes, str]] = []
    for owner, _order, contributions in owner_pairs:
        for contribution in contributions:
            slot = slots_by_id.get(contribution.slot)
            if slot is None:
                return Err(
                    RenderError(
                        RenderErrorKind.INVALID_TEMPLATE,
                        "missing_slot",
                        _identity(owner, contribution.id),
                    )
                )
            if (
                slot.allowed_contribution_kind is not None
                and contribution.kind != slot.allowed_contribution_kind
            ):
                return Err(
                    RenderError(
                        RenderErrorKind.INVALID_TEMPLATE,
                        "wrong_kind",
                        _identity(owner, contribution.id),
                    )
                )
            body = blobs.get(contribution.body_blob)
            if body is None:  # pragma: no cover - pre-checked by compose_contributions
                return Err(
                    RenderError(
                        RenderErrorKind.MISSING_BLOB,
                        "missing_body_blob",
                        _identity(owner, contribution.id),
                    )
                )
            raw.append((contribution, body, owner))
    owner_order_by_id = {owner: order for owner, order, _ in owner_pairs}
    ordered = sorted(
        raw,
        key=lambda entry: (
            entry[0].order,
            owner_order_by_id[entry[2]],
            entry[2],
            entry[0].id,
        ),
    )
    slot_ids: dict[str, tuple[str, ...]] = {}
    for contribution, _body, _owner in ordered:
        slot_ids[contribution.slot] = (
            *slot_ids.get(contribution.slot, ()),
            contribution.id,
        )
    resolved: list[ResolvedContribution] = []
    for contribution, body, owner in ordered:
        slot = slots_by_id[contribution.slot]
        match apply_substitutions(
            body,
            contribution.substitutions,
            context=slot.context,
            settings=settings,
            project=project,
            maintenance=maintenance,
            slot_ids=slot_ids,
        ):
            case Err(error):
                return Err(error)
            case Ok(rendered):
                try:
                    rendered_body = rendered.decode("utf-8")
                except UnicodeDecodeError:
                    return Err(
                        RenderError(
                            RenderErrorKind.INVALID_TEMPLATE,
                            "body_encoding",
                            _identity(owner, contribution.id),
                        )
                    )
                resolved.append(
                    ResolvedContribution(
                        slot=contribution.slot,
                        owner=owner,
                        contribution_id=contribution.id,
                        order=contribution.order,
                        kind=contribution.kind,
                        rendered_body=rendered_body,
                    )
                )
    return Ok(tuple(resolved))


def _fragment_pairs(
    core: CoreDefinition,
    definitions: Mapping[str, CapabilityDefinition],
    effective: tuple[str, ...],
) -> Result[
    tuple[tuple[str, int, tuple[DocumentFragmentDefinition, ...]], ...], RenderError
]:
    pairs: list[tuple[str, int, tuple[DocumentFragmentDefinition, ...]]] = [
        (CORE_OWNER, -1, core.document_fragments)
    ]
    for owner_order, capability_id in enumerate(effective):
        if capability_id == CORE_OWNER:
            return Err(
                RenderError(
                    RenderErrorKind.INVALID_TEMPLATE, "reserved_owner", capability_id
                )
            )
        definition = definitions.get(capability_id)
        if definition is None:
            return Err(
                RenderError(
                    RenderErrorKind.INVALID_TEMPLATE,
                    "missing_capability_definition",
                    capability_id,
                )
            )
        pairs.append((capability_id, owner_order, definition.document_fragments))
    return Ok(tuple(pairs))


def compose_document_bodies(
    core: CoreDefinition,
    definitions: Mapping[str, CapabilityDefinition],
    effective: tuple[str, ...],
    settings: Mapping[str, Mapping[str, SettingValue]],
    project: ProjectInfo,
    maintenance: MaintenanceInfo,
    blobs: VerifiedBlobStore,
    render_context: RenderContext | None = None,
) -> Result[tuple[tuple[RepoPath, tuple[str, ...]], ...], RenderError]:
    """Compose document-fragment bodies grouped by document, ordered by normative keys."""
    match _fragment_pairs(core, definitions, effective):
        case Err(error):
            return Err(error)
        case Ok(fragment_pairs):
            pass
    for owner, _order, fragments in fragment_pairs:
        for fragment in fragments:
            if blobs.get(fragment.body_blob) is None:
                return Err(
                    RenderError(
                        RenderErrorKind.MISSING_BLOB,
                        "",
                        _identity(owner, fragment.id),
                    )
                )
    identities: set[tuple[str, str]] = set()
    for owner, _order, fragments in fragment_pairs:
        for fragment in fragments:
            identity = (owner, fragment.id)
            if identity in identities:
                return Err(
                    RenderError(
                        RenderErrorKind.INVALID_TEMPLATE,
                        "duplicate_fragment_identity",
                        _identity(owner, fragment.id),
                    )
                )
            identities.add(identity)
    rendered: list[_RenderedFragment] = []
    for owner, owner_order, fragments in fragment_pairs:
        for fragment in fragments:
            body = blobs.get(fragment.body_blob)
            if (
                body is None
            ):  # pragma: no cover - pre-checked by compose_document_bodies
                return Err(
                    RenderError(
                        RenderErrorKind.MISSING_BLOB,
                        "missing_fragment_blob",
                        _identity(owner, fragment.id),
                    )
                )
            match apply_substitutions(
                body,
                fragment.substitutions,
                context="markdown",
                settings=settings,
                project=project,
                maintenance=maintenance,
                slot_ids={},
                render_context=render_context,
            ):
                case Err(error):
                    return Err(error)
                case Ok(rendered_body):
                    try:
                        text = rendered_body.decode("utf-8")
                    except UnicodeDecodeError:
                        return Err(
                            RenderError(
                                RenderErrorKind.INVALID_TEMPLATE,
                                "body_encoding",
                                _identity(owner, fragment.id),
                            )
                        )
                    rendered.append(
                        _RenderedFragment(
                            order=fragment.order,
                            owner_order=owner_order,
                            owner=owner,
                            fragment_id=fragment.id,
                            document=fragment.document,
                            text=text,
                        )
                    )
    ordered = sorted(
        rendered,
        key=lambda fragment: (
            fragment.order,
            fragment.owner_order,
            fragment.owner,
            fragment.fragment_id,
        ),
    )
    bodies_by_document: dict[str, list[str]] = {}
    for fragment in ordered:
        bodies_by_document.setdefault(fragment.document, []).append(fragment.text)
    result = tuple(
        (
            RepoPath(document),
            tuple(bodies),
        )
        for document, bodies in sorted(
            bodies_by_document.items(), key=lambda item: item[0].encode("utf-8")
        )
    )
    return Ok(result)


def render_generation(
    *,
    generation_path: GenerationPath,
    core: CoreDefinition,
    definitions: Mapping[str, CapabilityDefinition],
    effective: tuple[str, ...],
    additions: tuple[str, ...] = (),
    settings: Mapping[str, Mapping[str, SettingValue]],
    project: ProjectInfo,
    licensing: LicensingInfo,
    profile: ProfileInfo,
    maintenance: MaintenanceInfo,
    slots: Mapping[str, SlotContent],
    blobs: VerifiedBlobStore,
) -> Result[ManagedRender, RenderError]:
    """Compose and render the complete managed output for one selection.

    The single shared render entry point: it interns the capability fragment
    bodies, composes contributions and document fragments for the effective
    selection, builds the render input, and returns the verified managed
    files.  Callers map ``RenderError`` to their own surface -- the imperative
    shell wraps it as a contract violation; validators and fixtures raise it.
    """
    interned = blobs
    for content in template_bodies().values():
        match interned.intern(content):
            case Err(error):
                return Err(
                    RenderError(
                        RenderErrorKind.MISSING_BLOB, error.kind.value, error.subject
                    )
                )
            case Ok((_content_id, updated)):
                interned = updated
    match compose_contributions(
        core,
        definitions,
        effective,
        settings,
        project,
        maintenance,
        interned,
    ):
        case Err(error):
            return Err(error)
        case Ok(contributions):
            pass
    match compose_document_bodies(
        core,
        definitions,
        effective,
        settings,
        project,
        maintenance,
        interned,
        render_context=RenderContext(
            generation_path=generation_path,
            profile=profile,
            additions=additions,
            effective=effective,
            definitions=definitions,
            settings=settings,
        ),
    ):
        case Err(error):
            return Err(error)
        case Ok(documents):
            pass
    render_input = RenderInput(
        render_input_version=1,
        generation_path=generation_path,
        project=project,
        licensing=licensing,
        profile=profile,
        additions=additions,
        effective=effective,
        definitions=definitions,
        core=core,
        settings=settings,
        contributions=contributions,
        documents=dict(documents),
        maintenance=maintenance,
        slots=slots,
    )
    return render_managed(render_input, interned)


def render_source_fixture(
    selection: tuple[str, ...],
) -> Result[dict[str, bytes], RenderError]:
    """Render one pinned source workflow with the canonical source fixture.

    The source commits its ``.github/workflows`` files byte-for-byte to these
    renders, so both the shipped ``validate_template.py`` pin and the test
    suites share this single implementation and the frozen inputs (example
    project, retain-Apache-2.0, clean maintenance, custom profile, empty
    settings) never drift between them.
    """
    store = VerifiedBlobStore.empty()
    match render_generation(
        generation_path=GenerationPath.GITHUB,
        core=core_definition(),
        definitions=capability_definitions(),
        effective=selection,
        settings={},
        project=ProjectInfo(name="example", default_branch="main"),
        licensing=LicensingInfo(mode="retain-apache-2.0", content_sha256=None),
        profile=ProfileInfo(id="custom", frozen=selection),
        maintenance=MaintenanceInfo(status="clean", retained_paths=()),
        slots={},
        blobs=store,
    ):
        case Err(error):
            return Err(error)
        case Ok(managed):
            return Ok({file.path.value: file.content for file in managed})
