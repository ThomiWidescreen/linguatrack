from datetime import datetime, timezone
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class IDMixin:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class User(IDMixin, Base):
    __tablename__ = "users"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Language(Base):
    __tablename__ = "languages"
    tag: Mapped[str] = mapped_column(String(35), primary_key=True)
    name: Mapped[str]
    base_tag: Mapped[str]


class Track(IDMixin, Base):
    __tablename__ = "user_languages"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    language_tag: Mapped[str] = mapped_column(ForeignKey("languages.tag"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("user_id", "language_tag"),
        UniqueConstraint("user_id", "id"),
    )


class Lesson(IDMixin, Base):
    __tablename__ = "learning_sessions"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    track_id: Mapped[UUID]
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="manual")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bridge_languages: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    revision: Mapped[int] = mapped_column(default=1)
    published_run_id: Mapped[UUID | None]  # validated under session/track locks by publisher
    __table_args__ = (
        UniqueConstraint("user_id", "id"),
        ForeignKeyConstraint(
            ["user_id", "track_id"], ["user_languages.user_id", "user_languages.id"]
        ),
        Index("ix_sessions_user_created", "user_id", "created_at", "id"),
    )


class Run(IDMixin, Base):
    __tablename__ = "processing_runs"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    session_id: Mapped[UUID]
    revision: Mapped[int]
    status: Mapped[str] = mapped_column(String(30), default="queued")
    stage: Mapped[str] = mapped_column(String(30), default="validated")
    attempts: Mapped[int] = mapped_column(default=0)
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extraction: Mapped[dict | None] = mapped_column(JSONB)
    summary: Mapped[dict | None] = mapped_column(JSONB)
    review_required: Mapped[bool] = mapped_column(default=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str]
    extractor_version: Mapped[str] = mapped_column(default="lesson-v3")
    bridge_languages: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    resolver_version: Mapped[str] = mapped_column(default="lexical-v2")
    projector_version: Mapped[str] = mapped_column(default="counts-v1")
    provider_response_id: Mapped[str | None]
    usage: Mapped[dict | None] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("user_id", "id"),
        UniqueConstraint("session_id", "revision"),
        ForeignKeyConstraint(
            ["user_id", "session_id"], ["learning_sessions.user_id", "learning_sessions.id"]
        ),
        CheckConstraint(
            "status IN ('queued','running','retrying','completed','failed','superseded','needs_review')"
        ),
        Index("ix_runs_user_status", "user_id", "status", "created_at"),
    )


class RequestKey(IDMixin, Base):
    __tablename__ = "ingestion_requests"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    scope: Mapped[str]
    key: Mapped[str]
    request_hash: Mapped[str]
    session_id: Mapped[UUID]
    run_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("user_id", "scope", "key"),
        ForeignKeyConstraint(
            ["user_id", "session_id"], ["learning_sessions.user_id", "learning_sessions.id"]
        ),
        ForeignKeyConstraint(
            ["user_id", "run_id"], ["processing_runs.user_id", "processing_runs.id"]
        ),
    )


class Concept(IDMixin, Base):
    __tablename__ = "concepts"
    language_tag: Mapped[str] = mapped_column(ForeignKey("languages.tag"))
    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(30))
    lemma: Mapped[str]
    search_key: Mapped[str]
    pos: Mapped[str] = mapped_column(String(20))
    identity_key: Mapped[str] = mapped_column(unique=True)
    gloss: Mapped[str | None]
    status: Mapped[str] = mapped_column(default="provisional")
    __table_args__ = (
        Index("ix_concepts_lexical", "language_tag", "search_key", "kind", "pos"),
        CheckConstraint("kind IN ('lexeme','construction')"),
    )


class Observation(IDMixin, Base):
    __tablename__ = "learning_observations"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    run_id: Mapped[UUID]
    session_id: Mapped[UUID]
    concept_id: Mapped[UUID] = mapped_column(ForeignKey("concepts.id"))
    activity_key: Mapped[str]
    dimension: Mapped[str]
    activity: Mapped[str]
    correctness: Mapped[str]
    assistance: Mapped[str]
    actor: Mapped[str]
    quote: Mapped[str] = mapped_column(Text)
    span_start: Mapped[int]
    span_end: Mapped[int]
    confidence: Mapped[float]
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provenance: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("run_id", "activity_key", "concept_id", "dimension"),
        ForeignKeyConstraint(
            ["user_id", "run_id"], ["processing_runs.user_id", "processing_runs.id"]
        ),
        ForeignKeyConstraint(
            ["user_id", "session_id"], ["learning_sessions.user_id", "learning_sessions.id"]
        ),
        CheckConstraint("span_start >= 0 AND span_end > span_start"),
        CheckConstraint("confidence >= 0 AND confidence <= 1"),
        Index("ix_evidence_user_concept_time", "user_id", "concept_id", "occurred_at", "id"),
    )


class Knowledge(IDMixin, Base):
    __tablename__ = "user_knowledge_state"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    track_id: Mapped[UUID]
    concept_id: Mapped[UUID] = mapped_column(ForeignKey("concepts.id"))
    dimension: Mapped[str]
    encounters: Mapped[int]
    practice: Mapped[int]
    independent_correct: Mapped[int]
    assisted_correct: Mapped[int]
    incorrect: Mapped[int]
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str]
    projector_version: Mapped[str] = mapped_column(default="counts-v1")
    __table_args__ = (
        UniqueConstraint("track_id", "concept_id", "dimension"),
        ForeignKeyConstraint(
            ["user_id", "track_id"], ["user_languages.user_id", "user_languages.id"]
        ),
        Index("ix_knowledge_user_track", "user_id", "track_id", "id"),
    )


class Correction(IDMixin, Base):
    __tablename__ = "evidence_amendments"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    session_id: Mapped[UUID]
    fingerprint: Mapped[str]
    patch: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "session_id"], ["learning_sessions.user_id", "learning_sessions.id"]
        ),
    )


class Outbox(IDMixin, Base):
    __tablename__ = "outbox"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    run_id: Mapped[UUID]
    delivery_key: Mapped[str] = mapped_column(unique=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "run_id"], ["processing_runs.user_id", "processing_runs.id"]
        ),
        Index("ix_outbox_pending", "available_at", postgresql_where=published_at.is_(None)),
    )


class ReferenceBuild(IDMixin, Base):
    __tablename__ = "reference_builds"
    digest: Mapped[str] = mapped_column(unique=True)
    manifest: Mapped[dict] = mapped_column(JSONB)
    attribution: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReferenceAssertion(IDMixin, Base):
    __tablename__ = "reference_assertions"
    build_id: Mapped[UUID] = mapped_column(ForeignKey("reference_builds.id"))
    assertion_id: Mapped[str]
    kind: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSONB)
    concept_id: Mapped[UUID | None] = mapped_column(ForeignKey("concepts.id"))
    __table_args__ = (UniqueConstraint("build_id", "kind", "assertion_id"),)


class ConceptEmbedding(IDMixin, Base):
    """Reserved: no semantic identity decisions or automatic embedding calls in the MVP."""

    __tablename__ = "concept_embeddings"
    concept_id: Mapped[UUID] = mapped_column(ForeignKey("concepts.id"))
    model: Mapped[str]
    template_version: Mapped[str]
    content_hash: Mapped[str]
    embedding: Mapped[list[float]] = mapped_column(Vector(1536))
    __table_args__ = (UniqueConstraint("concept_id", "model", "template_version", "content_hash"),)
