"""Pure contribution and document-fragment composition for the render boundary.

Composition resolves contribution bodies and document-fragment bodies from verified blobs,
applies substitutions with the declared context encoder, and returns contributions in the
normative slot order. Every referenced blob must be present before any body is rendered.
"""

from __future__ import annotations

from collections.abc import Mapping

from scripts.bootstrap.blobs import VerifiedBlobStore
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.render import (
    CapabilityDefinition,
    ContributionDefinition,
    CoreDefinition,
    DocumentFragmentDefinition,
    MaintenanceInfo,
    ProjectInfo,
    RenderError,
    RenderErrorKind,
    ResolvedContribution,
    SettingValue,
    apply_substitutions,
)
from scripts.bootstrap.result import Err, Ok, Result

CORE_OWNER = "core"


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
    """Compose every effective contribution into the normative sorted order."""
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
    by_slot: dict[str, list[ResolvedContribution]] = {
        slot.id: [] for slot in core.slots
    }
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
            match apply_substitutions(
                body,
                contribution.substitutions,
                context=slot.context,
                settings=settings,
                project=project,
                maintenance=maintenance,
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
                    by_slot[contribution.slot].append(
                        ResolvedContribution(
                            slot=contribution.slot,
                            owner=owner,
                            contribution_id=contribution.id,
                            order=contribution.order,
                            kind=contribution.kind,
                            rendered_body=rendered_body,
                        )
                    )
    owner_order_by_id = {owner: order for owner, order, _ in owner_pairs}
    resolved = [
        contribution
        for contributions in by_slot.values()
        for contribution in contributions
    ]
    ordered = sorted(
        resolved,
        key=lambda contribution: (
            contribution.order,
            owner_order_by_id[contribution.owner],
            contribution.owner,
            contribution.contribution_id,
        ),
    )
    return Ok(tuple(ordered))


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
    rendered: list[tuple[int, int, str, str, str, str]] = []
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
                        (
                            fragment.order,
                            owner_order,
                            owner,
                            fragment.id,
                            fragment.document,
                            text,
                        )
                    )
    ordered = sorted(
        rendered,
        key=lambda item: (item[0], item[1], item[2], item[3]),
    )
    bodies_by_document: dict[str, list[str]] = {}
    for _order, _owner_order, _owner, _fragment_id, document, text in ordered:
        bodies_by_document.setdefault(document, []).append(text)
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
