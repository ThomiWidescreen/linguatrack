import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Activity = Literal[
    "exposure",
    "review",
    "recognition",
    "recall_attempt",
    "production_attempt",
    "practice_unspecified",
]
Correctness = Literal["correct", "incorrect", "partial", "unknown"]
Assistance = Literal["none", "hint", "full", "unknown"]
Dimension = Literal[
    "receptive_vocabulary",
    "productive_vocabulary",
    "reading",
    "listening",
    "writing",
    "speaking",
    "morphology",
    "grammar",
    "semantics",
    "unspecified",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedEvidence(StrictModel):
    lemma: str = Field(min_length=1, max_length=300)
    kind: Literal["lexeme", "construction"]
    pos: Literal[
        "ADJ",
        "ADP",
        "ADV",
        "AUX",
        "CCONJ",
        "DET",
        "INTJ",
        "NOUN",
        "NUM",
        "PART",
        "PRON",
        "PROPN",
        "PUNCT",
        "SCONJ",
        "SYM",
        "VERB",
        "X",
    ]
    gloss: str | None
    language_tag: str
    quote: str = Field(min_length=1, max_length=10000)
    quote_occurrence: int = Field(ge=0, le=1000)
    activity: Activity
    correctness: Correctness
    assistance: Assistance
    actor: Literal["student", "teacher", "unknown"]
    dimension: Dimension
    confidence: float = Field(ge=0, le=1)

    @field_validator("lemma")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("lemma must not be blank")
        return value.strip()


class Extraction(StrictModel):
    items: list[ExtractedEvidence] = Field(max_length=500)
    warnings: list[str] = Field(max_length=100)


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def fingerprint(item: ExtractedEvidence) -> str:
    return digest(
        {
            k: getattr(item, k)
            for k in (
                "lemma",
                "kind",
                "pos",
                "quote",
                "quote_occurrence",
                "dimension",
                "activity",
            )
        }
    )


class TrackCreate(StrictModel):
    language_tag: str = Field(examples=["ms"])


class SessionCreate(StrictModel):
    text: str = Field(
        min_length=1,
        examples=[
            "Today we learned walaupun (although), terpaksa (being forced to), and sempat "
            "(having time to do something). We practiced using walaupun in concessive sentences."
        ],
    )
    title: str = Field(default="Clase", min_length=1, max_length=200)
    occurred_at: datetime | None = None

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("text must not be blank")
        return value

    @field_validator("occurred_at")
    @classmethod
    def aware(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class ReprocessRequest(StrictModel):
    expected_revision: int = Field(ge=1)


class CorrectionRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    observation_id: UUID
    discard: bool = False
    correctness: Correctness | None = None
    assistance: Assistance | None = None
    reason: str = Field(min_length=1, max_length=1000)


class Accepted(BaseModel):
    session_id: UUID
    run_id: UUID
    revision: int
    status_url: str


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TrackView(ORMModel):
    id: UUID
    language_tag: str
    created_at: datetime


class LanguageView(ORMModel):
    tag: str
    name: str
    base_tag: str


class SessionView(ORMModel):
    id: UUID
    track_id: UUID
    title: str
    source: str
    occurred_at: datetime | None
    created_at: datetime
    revision: int
    published_run_id: UUID | None


class SessionDetail(SessionView):
    text: str


class RunView(ORMModel):
    id: UUID
    session_id: UUID
    revision: int
    status: str
    stage: str
    attempts: int
    error_code: str | None
    review_required: bool
    model: str
    extractor_version: str
    resolver_version: str
    projector_version: str
    created_at: datetime
    finished_at: datetime | None
    summary: dict | None


class EvidenceView(ORMModel):
    id: UUID
    session_id: UUID
    run_id: UUID
    concept_id: UUID
    activity: str
    dimension: str
    correctness: str
    assistance: str
    actor: str
    quote: str
    span_start: int
    span_end: int
    occurred_at: datetime
    provenance: dict
