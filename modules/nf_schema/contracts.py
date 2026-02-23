from __future__ import annotations

from typing import Protocol

from modules.nf_shared.protocol.dtos import (
    Chunk,
    DocSnapshot,
    EntityID,
    ProjectID,
    SchemaFact,
    TagAssignment,
)


class Chunker(Protocol):
    def build_chunks(self, snapshot: DocSnapshot) -> list[Chunk]: ...


class IdentityResolver(Protocol):
    def resolve_entity(self, project_id: ProjectID, name: str, *, kind: str | None = None) -> EntityID | None: ...


class FactExtractor(Protocol):
    def extract_explicit(self, snapshot: DocSnapshot, assignments: list[TagAssignment]) -> list[SchemaFact]: ...

    def extract_implicit(self, snapshot: DocSnapshot) -> list[SchemaFact]: ...

