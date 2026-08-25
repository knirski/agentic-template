"""Shared fixture builders for the lifecycle transition suites.

The add/restore/reconcile suites render the same portable project and observe
the same managed target; the shared constants and builders live here so the
three files do not re-define them with silent drift between copies.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from scripts.bootstrap.blobs import VerifiedBlobStore
from scripts.bootstrap.capability_fragments import (
    capability_definitions,
    core_definition,
)
from scripts.bootstrap.contributions import render_generation
from scripts.bootstrap.identity import (
    DirectoryState,
    PosixMode,
    file_state_identity,
    sha256_hex,
    target_identity,
)
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.manifest import (
    LicensingRecord,
    ManifestAnswers,
    ProfileSelection,
    ProjectFacts,
    SlotContent,
)
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.planner import (
    SLOT_PLACEHOLDER_RULES,
    ObservedDirectoryEntry,
    ObservedFileEntry,
    TargetSnapshot,
)
from scripts.bootstrap.render import (
    LicensingInfo,
    MaintenanceInfo,
    ManagedFile,
    ProfileInfo,
    ProjectInfo,
)
from scripts.bootstrap.result import Err, Ok
from scripts.bootstrap.scaffold import PROJECT_VALIDATION_SCAFFOLD
from scripts.bootstrap.source_baseline import (
    CopierSourceBaseline,
    GitHubSourceBaseline,
    LifecycleSourceEntry,
    template_source_fingerprint,
)

TARGET = target_identity(b"/work/example", device=1, inode=2)
PROJECT = ProjectInfo(name="example", default_branch="main")
LICENSING = LicensingInfo(mode="retain-apache-2.0", content_sha256=None)
PROFILE = ProfileInfo(id="portable", frozen=())
MAINTENANCE_INFO = MaintenanceInfo(status="clean", retained_paths=())
SLOTS: Mapping[str, SlotContent] = MappingProxyType({})
SOURCE_ENTRIES = (
    LifecycleSourceEntry(
        path=RepoPath("scripts/bootstrap/__init__.py"),
        kind="file",
        mode=PosixMode.FILE,
        sha256=sha256_hex(b"present\n"),
    ),
    LifecycleSourceEntry(
        path=RepoPath("scripts/bootstrap/render.py"),
        kind="file",
        mode=PosixMode.FILE,
        sha256=sha256_hex(b"present\n"),
    ),
)
SLOT_CONTENTS: dict[str, bytes] = {
    "readme": b"# Example\n\nReal project description.\n",
    "prd": b"<!-- rygor:placeholder:prd -->\n# Product\n",
    "security_policy": b"<!-- rygor:placeholder:security -->\n",
    "contributing": b"<!-- rygor:placeholder:contributing -->\n",
    "validation_hook": (
        b"#!/usr/bin/env python3\nrygor:unconfigured:validate-project\n"
    ),
    "project_validation": PROJECT_VALIDATION_SCAFFOLD,
}


def render_for(
    effective: tuple[str, ...],
    generation: GenerationPath,
    settings: Mapping[str, Mapping[str, str | bool]] | None = None,
) -> tuple[tuple[ManagedFile, ...], VerifiedBlobStore]:
    blobs = VerifiedBlobStore.empty()
    match render_generation(
        generation_path=generation,
        core=core_definition(),
        definitions=capability_definitions(),
        effective=effective,
        settings=settings or MappingProxyType({}),
        project=PROJECT,
        licensing=LICENSING,
        profile=PROFILE,
        maintenance=MAINTENANCE_INFO,
        slots=SLOTS,
        blobs=blobs,
    ):
        case Ok(rendered):
            return rendered, blobs
        case Err(error):
            raise AssertionError(f"render failed: {error}")


def fixture_answers() -> ManifestAnswers:
    slots: dict[str, SlotContent] = {}
    for rule in SLOT_PLACEHOLDER_RULES:
        if rule.slot == "prd":
            slots[rule.slot] = SlotContent(mode="scaffold", content_sha256=None)
        else:
            slots[rule.slot] = SlotContent(
                mode="file", content_sha256=sha256_hex(SLOT_CONTENTS[rule.slot])
            )
    slots["project_validation"] = SlotContent(mode="scaffold", content_sha256=None)
    return ManifestAnswers(
        project=ProjectFacts(name="example", default_branch="main"),
        profile=ProfileSelection(id="portable", requested=()),
        settings=MappingProxyType({}),
        licensing=LicensingRecord(mode="retain-apache-2.0", content_sha256=None),
        slots=MappingProxyType(slots),
    )


def github_source_baseline() -> GitHubSourceBaseline:
    return GitHubSourceBaseline(
        kind="github",
        fingerprint=template_source_fingerprint(SOURCE_ENTRIES),
        entries=SOURCE_ENTRIES,
        snapshot_commit="0" * 40,
    )


def copier_source_baseline(seed: bytes) -> CopierSourceBaseline:
    entries = (
        LifecycleSourceEntry(
            path=SOURCE_ENTRIES[0].path,
            kind=SOURCE_ENTRIES[0].kind,
            mode=SOURCE_ENTRIES[0].mode,
            sha256=sha256_hex(seed),
        ),
        *SOURCE_ENTRIES[1:],
    )
    return CopierSourceBaseline(
        kind="copier",
        fingerprint=template_source_fingerprint(entries),
        entries=entries,
    )


def observed_snapshot(
    managed: tuple[ManagedFile, ...], *, drift: Mapping[str, bytes] | None = None
) -> TargetSnapshot:
    drifted = drift or {}
    files: list[ObservedFileEntry] = []
    directories: dict[str, ObservedDirectoryEntry] = {}
    for file in managed:
        content = drifted.get(file.path.value, file.content)
        files.append(
            ObservedFileEntry(
                path=file.path,
                state=file_state_identity(
                    content, text=file.kind == "text", mode=file.mode
                ),
                content=content,
            )
        )
        if "/" not in file.path.value:
            continue
        parent = file.path.value.rsplit("/", 1)[0]
        while parent:
            if parent not in directories:
                directories[parent] = ObservedDirectoryEntry(
                    path=RepoPath(parent), state=DirectoryState(PosixMode.DIRECTORY, ())
                )
            if "/" not in parent:
                break
            parent = parent.rsplit("/", 1)[0]
    return TargetSnapshot(
        files=tuple(sorted(files, key=lambda e: e.path.value.encode("utf-8"))),
        directories=tuple(
            sorted(directories.values(), key=lambda e: e.path.value.encode("utf-8"))
        ),
    )
