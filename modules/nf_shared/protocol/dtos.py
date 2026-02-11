from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


AppTimestamp = str

ProjectID = str
DocID = str
SnapshotID = str
ChunkID = str
EpisodeID = str
JobID = str
EvidenceID = str
VerdictID = str
EntityID = str
TagID = str
FactID = str
MentionID = str
AnchorID = str
TimelineEventID = str
ExtractionMappingID = str


class DocumentType(str, Enum):
    SETTING = "SETTING"
    PLOT = "PLOT"
    CHAR = "CHAR"
    EPISODE = "EPISODE"
    NOTE = "NOTE"


class TagKind(str, Enum):
    EXPLICIT = "EXPLICIT"
    IMPLICIT = "IMPLICIT"
    USER = "USER"


class SchemaType(str, Enum):
    INT = "int"
    FLOAT = "float"
    STR = "str"
    ENUM = "enum"
    TIME = "time"
    LOC = "loc"
    REL = "rel"
    BOOL = "bool"
    UNKNOWN = "unknown"


class FactStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FactSource(str, Enum):
    USER = "USER"
    AUTO = "AUTO"


class EvidenceMatchType(str, Enum):
    EXACT = "EXACT"
    FUZZY = "FUZZY"
    ALIAS = "ALIAS"


class EvidenceRole(str, Enum):
    SUPPORT = "SUPPORT"
    CONTRADICT = "CONTRADICT"


class Verdict(str, Enum):
    OK = "OK"
    VIOLATE = "VIOLATE"
    UNKNOWN = "UNKNOWN"


class JobType(str, Enum):
    INGEST = "INGEST"
    INDEX_FTS = "INDEX_FTS"
    INDEX_VEC = "INDEX_VEC"
    CONSISTENCY = "CONSISTENCY"
    RETRIEVE_VEC = "RETRIEVE_VEC"
    SUGGEST = "SUGGEST"
    PROOFREAD = "PROOFREAD"
    EXPORT = "EXPORT"


class JobStatus(str, Enum):
    NEW = "NEW"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    PAUSED = "PAUSED"
    RETRYING = "RETRYING"


class JobEventLevel(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    PROGRESS = "PROGRESS"


class SuggestMode(str, Enum):
    LOCAL_RULE = "LOCAL_RULE"
    API = "API"
    LOCAL_GEN = "LOCAL_GEN"


class EntityKind(str, Enum):
    CHAR = "CHAR"
    LOC = "LOC"
    ORG = "ORG"
    OBJ = "OBJ"
    EVENT = "EVENT"


@dataclass(frozen=True)
class Project:
    project_id: ProjectID
    name: str
    created_at: AppTimestamp
    settings: Mapping[str, Any]


@dataclass(frozen=True)
class Document:
    doc_id: DocID
    project_id: ProjectID
    title: str
    type: DocumentType
    path: str
    head_snapshot_id: SnapshotID
    checksum: str
    version: int
    created_at: AppTimestamp
    updated_at: AppTimestamp
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class DocSnapshot:
    snapshot_id: SnapshotID
    project_id: ProjectID
    doc_id: DocID
    version: int
    path: str
    checksum: str
    created_at: AppTimestamp


@dataclass(frozen=True)
class Episode:
    episode_id: EpisodeID
    project_id: ProjectID
    start_n: int
    end_m: int
    label: str
    created_at: AppTimestamp


@dataclass(frozen=True)
class Chunk:
    chunk_id: ChunkID
    project_id: ProjectID
    doc_id: DocID
    snapshot_id: SnapshotID
    section_path: str
    episode_id: EpisodeID | None
    span_start: int
    span_end: int
    token_count_est: int | None
    created_by: FactSource
    created_at: AppTimestamp


@dataclass(frozen=True)
class Section:
    section_id: str
    project_id: ProjectID
    doc_id: DocID
    snapshot_id: SnapshotID
    section_path: str
    span_start: int
    span_end: int


@dataclass(frozen=True)
class TagDef:
    tag_id: TagID
    project_id: ProjectID
    tag_path: str
    kind: TagKind
    schema_type: SchemaType
    constraints: Mapping[str, Any]


@dataclass(frozen=True)
class TagAssignment:
    assign_id: str
    project_id: ProjectID
    doc_id: DocID
    snapshot_id: SnapshotID
    span_start: int
    span_end: int
    tag_path: str
    user_value: Any
    created_by: FactSource
    created_at: AppTimestamp


@dataclass(frozen=True)
class Entity:
    entity_id: EntityID
    project_id: ProjectID
    kind: EntityKind
    canonical_name: str
    created_at: AppTimestamp


@dataclass(frozen=True)
class EntityAlias:
    alias_id: str
    project_id: ProjectID
    entity_id: EntityID
    alias_text: str
    created_by: FactSource
    created_at: AppTimestamp


@dataclass(frozen=True)
class SchemaVersion:
    schema_ver: str
    project_id: ProjectID
    created_at: AppTimestamp
    source_snapshot_id: SnapshotID
    notes: str | None


class SchemaLayer(str, Enum):
    EXPLICIT = "explicit"
    IMPLICIT = "implicit"


@dataclass(frozen=True)
class SchemaFact:
    fact_id: FactID
    project_id: ProjectID
    schema_ver: str
    layer: SchemaLayer
    entity_id: EntityID | None
    tag_path: str
    value: Any
    evidence_eid: EvidenceID
    confidence: float
    source: FactSource
    status: FactStatus


@dataclass(frozen=True)
class SchemaView:
    project_id: ProjectID
    schema_ver: str
    facts: tuple[SchemaFact, ...]
    created_at: AppTimestamp


@dataclass(frozen=True)
class Evidence:
    eid: EvidenceID
    project_id: ProjectID
    doc_id: DocID
    snapshot_id: SnapshotID
    chunk_id: ChunkID | None
    section_path: str
    tag_path: str
    snippet_text: str
    span_start: int
    span_end: int
    fts_score: float
    match_type: EvidenceMatchType
    confirmed: bool
    created_at: AppTimestamp


@dataclass(frozen=True)
class EntityMentionSpan:
    mention_id: MentionID
    project_id: ProjectID
    doc_id: DocID
    snapshot_id: SnapshotID
    entity_id: EntityID
    span_start: int
    span_end: int
    status: FactStatus
    created_by: FactSource
    created_at: AppTimestamp


@dataclass(frozen=True)
class TimeAnchor:
    anchor_id: AnchorID
    project_id: ProjectID
    doc_id: DocID
    snapshot_id: SnapshotID
    span_start: int
    span_end: int
    time_key: str
    timeline_idx: int | None
    status: FactStatus
    created_by: FactSource
    created_at: AppTimestamp


@dataclass(frozen=True)
class TimelineEvent:
    timeline_event_id: TimelineEventID
    project_id: ProjectID
    timeline_idx: int
    label: str
    time_key: str
    source_doc_id: DocID
    source_snapshot_id: SnapshotID
    span_start: int
    span_end: int
    status: FactStatus
    created_by: FactSource
    created_at: AppTimestamp


@dataclass(frozen=True)
class ExtractionMapping:
    mapping_id: ExtractionMappingID
    project_id: ProjectID
    slot_key: str
    pattern: str
    flags: str
    transform: str
    priority: int
    enabled: bool
    created_by: str
    created_at: AppTimestamp


@dataclass(frozen=True)
class Span:
    start: int
    end: int


@dataclass(frozen=True)
class ReliabilityBreakdown:
    fts_strength: float
    evidence_count: int
    confirmed_evidence: int
    model_score: float


@dataclass(frozen=True)
class VerdictLog:
    vid: VerdictID
    project_id: ProjectID
    input_doc_id: DocID
    input_snapshot_id: SnapshotID
    schema_ver: str
    segment_span: Span
    claim_text: str
    verdict: Verdict
    reliability_overall: float
    breakdown: ReliabilityBreakdown
    whitelist_applied: bool
    created_at: AppTimestamp


@dataclass(frozen=True)
class VerdictEvidenceLink:
    vid: VerdictID
    eid: EvidenceID
    role: EvidenceRole


@dataclass(frozen=True)
class Job:
    job_id: JobID
    type: JobType
    project_id: ProjectID
    status: JobStatus
    created_at: AppTimestamp
    queued_at: AppTimestamp | None = None
    started_at: AppTimestamp | None = None
    finished_at: AppTimestamp | None = None


@dataclass(frozen=True)
class JobEvent:
    event_id: str
    job_id: JobID
    ts: AppTimestamp
    level: JobEventLevel
    message: str
    progress: float | None = None
    metrics: Mapping[str, Any] | None = None
    payload: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class LintItem:
    span_start: int
    span_end: int
    rule_id: str
    severity: str
    message: str
    suggestion: str | None = None


@dataclass(frozen=True)
class Citation:
    doc_id: DocID
    snapshot_id: SnapshotID
    tag_path: str
    section_path: str
    snippet_text: str


@dataclass(frozen=True)
class Suggestion:
    suggestion_id: str
    project_id: ProjectID
    mode: SuggestMode
    text: str
    citations: tuple[Citation, ...]
    created_at: AppTimestamp
