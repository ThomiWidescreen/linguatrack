import unicodedata
from collections import defaultdict
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from linguatrack.config import get_settings
from linguatrack.db import advisory_lock
from linguatrack.extraction import ExtractionFailure, span_for
from linguatrack.integrations import ADAPTERS
from linguatrack.models import (
    Concept,
    Correction,
    Knowledge,
    Language,
    Lesson,
    Observation,
    Outbox,
    RequestKey,
    Run,
    Track,
    User,
    now,
)
from linguatrack.schemas import (
    Accepted,
    CorrectionRequest,
    Extraction,
    ReprocessRequest,
    SessionCreate,
    digest,
    fingerprint,
)


class DomainError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def owned(db: Session, model, object_id: UUID, user_id: UUID):
    result = db.scalar(select(model).where(model.id == object_id, model.user_id == user_id))
    if result is None:
        raise DomainError(404, "Resource not found")
    return result


def ensure_user(db: Session, user_id: UUID):
    advisory_lock(db, f"user:{user_id}")
    if db.get(User, user_id) is None:
        db.add(User(id=user_id))
        db.flush()


def create_track(db: Session, user_id: UUID, language_tag: str):
    ensure_user(db, user_id)
    if db.get(Language, language_tag) is None:
        raise DomainError(422, "Unsupported language tag")
    if db.scalar(select(Track).where(Track.user_id == user_id, Track.language_tag == language_tag)):
        raise DomainError(409, "Language is already being tracked")
    track = Track(user_id=user_id, language_tag=language_tag)
    db.add(track)
    db.flush()
    return track


def accepted(lesson: Lesson, run: Run):
    return Accepted(
        session_id=lesson.id,
        run_id=run.id,
        revision=run.revision,
        status_url=f"/v1/me/processing-runs/{run.id}",
    )


def idempotent(db, user_id, scope, key, body):
    advisory_lock(db, f"request:{user_id}:{scope}:{key}")
    previous = db.scalar(
        select(RequestKey).where(
            RequestKey.user_id == user_id,
            RequestKey.scope == scope,
            RequestKey.key == key,
        )
    )
    if previous:
        if previous.request_hash != digest(body):
            raise DomainError(409, "Idempotency-Key already used with a different payload")
        return accepted(
            owned(db, Lesson, previous.session_id, user_id),
            owned(db, Run, previous.run_id, user_id),
        )
    return None


def enqueue(db, run: Run, key: str):
    db.add(
        Outbox(
            user_id=run.user_id,
            run_id=run.id,
            delivery_key=key,
            available_at=run.available_at,
        )
    )


def record_request(db, user_id, scope, key, body, lesson, run):
    db.add(
        RequestKey(
            user_id=user_id,
            scope=scope,
            key=key,
            request_hash=digest(body),
            session_id=lesson.id,
            run_id=run.id,
        )
    )
    enqueue(db, run, f"initial:{run.id}")
    return accepted(lesson, run)


def submit(db: Session, user_id: UUID, track_id: UUID, body: SessionCreate, key: str):
    track = owned(db, Track, track_id, user_id)
    scope = f"submit:{track.id}"
    payload = body.model_dump(mode="json")
    if not body.bridge_languages:
        # Preserve hashes of requests accepted before bridge context was introduced.
        payload.pop("bridge_languages")
    cached = idempotent(db, user_id, scope, key, payload)
    if cached:
        return cached
    if len(body.text) > get_settings().max_text_characters:
        raise DomainError(413, "Lesson exceeds configured text limit")
    validate_bridge_languages(track.language_tag, body.bridge_languages)
    envelope = ADAPTERS["manual"].normalize(
        {
            "language_tag": track.language_tag,
            "text": body.text,
            "bridge_languages": body.bridge_languages,
        }
    )
    lesson = Lesson(
        user_id=user_id,
        track_id=track.id,
        text=envelope.text,
        title=body.title,
        occurred_at=body.occurred_at,
        bridge_languages=envelope.bridge_languages,
    )
    db.add(lesson)
    db.flush()
    run = Run(
        user_id=user_id,
        session_id=lesson.id,
        revision=1,
        model=get_settings().openai_model,
        bridge_languages=envelope.bridge_languages,
    )
    db.add(run)
    db.flush()
    return record_request(db, user_id, scope, key, payload, lesson, run)


def validate_bridge_languages(target: str, bridges: list[str]):
    if any(tag.split("-")[0] == target.split("-")[0] for tag in bridges):
        raise DomainError(422, "Target language cannot also be a bridge language")


def new_revision(db, lesson, extraction=None, bridge_languages=None):
    previous = db.scalar(
        select(Run).where(
            Run.session_id == lesson.id,
            Run.user_id == lesson.user_id,
            Run.revision == lesson.revision,
        )
    )
    bridges = (
        bridge_languages
        if bridge_languages is not None
        else (previous.bridge_languages if previous else lesson.bridge_languages)
    )
    lesson.revision += 1
    run = Run(
        user_id=lesson.user_id,
        session_id=lesson.id,
        revision=lesson.revision,
        extraction=extraction,
        model=get_settings().openai_model,
        bridge_languages=bridges,
    )
    db.add(run)
    db.flush()
    return run


def reprocess(db, user_id, session_id, body: ReprocessRequest, key):
    lesson = owned(db, Lesson, session_id, user_id)
    scope = f"reprocess:{lesson.id}"
    payload = body.model_dump(mode="json")
    if body.bridge_languages is None:
        payload.pop("bridge_languages")
    cached = idempotent(db, user_id, scope, key, payload)
    if cached:
        return cached
    advisory_lock(db, f"track:{lesson.track_id}")
    db.refresh(lesson)
    if lesson.revision != body.expected_revision:
        raise DomainError(409, "Session revision has changed")
    track = owned(db, Track, lesson.track_id, user_id)
    validate_bridge_languages(track.language_tag, body.bridge_languages or [])
    run = new_revision(db, lesson, bridge_languages=body.bridge_languages)
    return record_request(db, user_id, scope, key, payload, lesson, run)


def correct(db, user_id, session_id, body: CorrectionRequest, key):
    lesson = owned(db, Lesson, session_id, user_id)
    scope = f"correction:{lesson.id}"
    payload = body.model_dump(mode="json")
    cached = idempotent(db, user_id, scope, key, payload)
    if cached:
        return cached
    advisory_lock(db, f"track:{lesson.track_id}")
    db.refresh(lesson)
    if lesson.revision != body.expected_revision:
        raise DomainError(409, "Session revision has changed")
    observation = owned(db, Observation, body.observation_id, user_id)
    if observation.session_id != lesson.id or observation.run_id != lesson.published_run_id:
        raise DomainError(409, "Observation must belong to the currently published session")
    patch = body.model_dump(include={"discard", "correctness", "assistance"}, exclude_none=True)
    if not body.discard and body.correctness is None and body.assistance is None:
        raise DomainError(422, "Specify a correction or discard=true")
    current = owned(db, Run, lesson.published_run_id, user_id)
    db.add(
        Correction(
            user_id=user_id,
            session_id=lesson.id,
            fingerprint=observation.provenance["fingerprint"],
            patch=patch,
            reason=body.reason,
        )
    )
    run = new_revision(
        db,
        lesson,
        extraction=current.extraction,
        bridge_languages=current.bridge_languages,
    )
    run.model = current.model
    run.extractor_version = current.extractor_version
    run.provider_response_id = current.provider_response_id
    run.usage = current.usage
    return record_request(db, user_id, scope, key, payload, lesson, run)


def normalize(value: str):
    return unicodedata.normalize("NFC", value).strip().casefold()


def resolve(db: Session, user_id: UUID, language: str, item):
    search_key = normalize(item.lemma)
    # Conjunction tagging varies between SCONJ/CCONJ in source/model annotations.
    # Track the lexical item together while preserving the original analysis in evidence.
    # This does not transfer knowledge of its grammatical functions.
    pos_family = "CONJ" if item.pos in {"SCONJ", "CCONJ"} else item.pos
    positions = ["SCONJ", "CCONJ"] if pos_family == "CONJ" else [item.pos]
    identity = digest([str(user_id), language, item.kind, search_key, pos_family])
    advisory_lock(db, f"concept:{user_id}:{language}:{item.kind}:{search_key}:{pos_family}")
    canonical_private = db.scalar(select(Concept).where(Concept.identity_key == identity))
    if canonical_private:
        return canonical_private, "private_exact"
    candidates = list(
        db.scalars(
            select(Concept).where(
                Concept.language_tag == language,
                Concept.search_key == search_key,
                Concept.kind == item.kind,
                Concept.pos.in_(positions),
                or_(Concept.owner_user_id == user_id, Concept.owner_user_id.is_(None)),
            )
        )
    )
    private = [c for c in candidates if c.owner_user_id == user_id]
    # Keep already encountered private identities stable across reference imports.
    if len(private) == 1:
        return private[0], "private_exact"
    public = [c for c in candidates if c.owner_user_id is None]
    if len(public) == 1:
        return public[0], "reference_exact_lexeme"
    concept = Concept(
        owner_user_id=user_id,
        language_tag=language,
        kind=item.kind,
        lemma=unicodedata.normalize("NFC", item.lemma),
        search_key=search_key,
        pos=item.pos,
        identity_key=identity,
        gloss=item.gloss,
    )
    db.add(concept)
    db.flush()
    return concept, "ambiguous_reference_provisional" if public else "private_provisional"


PRACTICE = {"recognition", "recall_attempt", "production_attempt", "practice_unspecified"}
ACTIVITY_ORDER = {
    "exposure": 0,
    "review": 1,
    "practice_unspecified": 2,
    "recognition": 3,
    "recall_attempt": 4,
    "production_attempt": 5,
}


def rebuild_knowledge(db: Session, user_id: UUID, track_id: UUID):
    """Replay the effective publications. MVP rebuilds one track under its transaction lock."""
    rows = list(
        db.scalars(
            select(Observation)
            .join(
                Lesson,
                Lesson.published_run_id == Observation.run_id,
            )
            .where(Lesson.user_id == user_id, Lesson.track_id == track_id)
            .order_by(
                Observation.occurred_at,
                Observation.id,
            )
        )
    )
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row.concept_id, row.dimension)].append(row)
    db.execute(
        delete(Knowledge).where(Knowledge.user_id == user_id, Knowledge.track_id == track_id)
    )
    for (concept_id, dimension), observations in grouped.items():
        practice = [o for o in observations if o.activity in PRACTICE and o.actor == "student"]
        independent = sum(o.correctness == "correct" and o.assistance == "none" for o in practice)
        assisted = sum(
            o.correctness == "correct" and o.assistance in {"hint", "full"} for o in practice
        )
        incorrect = sum(o.correctness == "incorrect" for o in practice)
        db.add(
            Knowledge(
                user_id=user_id,
                track_id=track_id,
                concept_id=concept_id,
                dimension=dimension,
                encounters=len(observations),
                practice=len(practice),
                independent_correct=independent,
                assisted_correct=assisted,
                incorrect=incorrect,
                first_seen=observations[0].occurred_at,
                last_seen=observations[-1].occurred_at,
                state="demonstrated" if independent else "practiced" if practice else "encountered",
            )
        )
    db.flush()


def publish(db: Session, run: Run):
    lesson = owned(db, Lesson, run.session_id, run.user_id)
    advisory_lock(db, f"track:{lesson.track_id}")
    db.refresh(lesson)
    if lesson.revision != run.revision:
        run.status = "superseded"
        run.finished_at = now()
        return
    track = owned(db, Track, lesson.track_id, run.user_id)
    extraction = Extraction.model_validate(run.extraction)
    amendments = list(
        db.scalars(
            select(Correction)
            .where(
                Correction.user_id == run.user_id,
                Correction.session_id == lesson.id,
            )
            .order_by(Correction.created_at, Correction.id)
        )
    )
    available = {fingerprint(item) for item in extraction.items}
    if any(a.fingerprint not in available for a in amendments):
        run.status, run.error_code, run.review_required = (
            "needs_review",
            "correction_anchor_changed",
            True,
        )
        run.finished_at = now()
        return  # Existing publication remains effective until corrections can be reconciled.
    patches = defaultdict(dict)
    for amendment in amendments:
        patches[amendment.fingerprint].update(amendment.patch)
    earlier = set(
        db.scalars(
            select(Observation.concept_id)
            .join(
                Lesson,
                Lesson.published_run_id == Observation.run_id,
            )
            .where(
                Lesson.user_id == run.user_id,
                Lesson.track_id == track.id,
                Lesson.created_at < lesson.created_at,
            )
        )
    )
    observations = {}
    concepts = {}
    review = bool(extraction.warnings)
    resolution_warnings = set()
    for raw in extraction.items:
        fp = fingerprint(raw)
        patch = patches[fp]
        if patch.get("discard"):
            continue
        item = raw.model_copy(update={k: v for k, v in patch.items() if k != "discard"})
        if item.kind == "construction" and len(item.lemma.split()) == 1 and item.pos != "X":
            # A bare lexical item with lexical POS is not a syntactic pattern.
            item = item.model_copy(update={"kind": "lexeme"})
            review = True
            resolution_warnings.add("Bare lexical label normalized from construction to lexeme.")
        if item.language_tag != track.language_tag:
            raise ExtractionFailure("extracted_language_mismatch")
        start, end = span_for(lesson.text, item.quote, item.quote_occurrence)
        concept, resolution = resolve(db, run.user_id, track.language_tag, item)
        concepts[concept.id] = concept
        review |= resolution == "ambiguous_reference_provisional"
        # Unknown/teacher attribution cannot demonstrate student success.
        activity, correctness, assistance = item.activity, item.correctness, item.assistance
        if item.actor != "student":
            activity, correctness, assistance = "exposure", "unknown", "unknown"
        if activity in {"exposure", "review", "practice_unspecified"}:
            correctness = "unknown"
        activity_key = digest([start, end])
        group = (concept.id, activity_key, item.dimension)
        row = Observation(
            user_id=run.user_id,
            run_id=run.id,
            session_id=lesson.id,
            concept_id=concept.id,
            activity_key=activity_key,
            dimension=item.dimension,
            activity=activity,
            correctness=correctness,
            assistance=assistance,
            actor=item.actor,
            quote=item.quote,
            span_start=start,
            span_end=end,
            confidence=item.confidence,
            occurred_at=lesson.occurred_at or lesson.created_at,
            provenance={
                "source": lesson.source,
                "observation_mode": "reported",
                "time_basis": "activity" if lesson.occurred_at else "received",
                "extractor": run.extractor_version,
                "model": run.model,
                "resolver": run.resolver_version,
                "resolution": resolution,
                "confidence_basis": "uncalibrated_extraction_heuristic",
                "extracted_kind": raw.kind,
                "extracted_pos": raw.pos,
                "human_corrected": bool(patch),
                "target_language": track.language_tag,
                "bridge_languages": run.bridge_languages,
                "fingerprint": fp,
            },
        )
        old = observations.get(group)
        if old is None or ACTIVITY_ORDER[activity] > ACTIVITY_ORDER[old.activity]:
            observations[group] = row
        elif old.activity == row.activity and old.correctness != row.correctness:
            old.correctness = "unknown"
            review = True
    db.add_all(observations.values())
    db.flush()
    lesson.published_run_id = run.id
    db.flush()
    rebuild_knowledge(db, run.user_id, track.id)

    def view(concept):
        return {"concept_id": str(concept.id), "lemma": concept.lemma, "kind": concept.kind}

    run.summary = {
        "language_context": {
            "target_language": track.language_tag,
            "bridge_languages": run.bridge_languages,
            "bridge_mode": "declared" if run.bridge_languages else "automatic",
        },
        "new_to_recorded_history": [view(c) for cid, c in concepts.items() if cid not in earlier],
        "revisited": [view(c) for cid, c in concepts.items() if cid in earlier],
        "observation_count": len(observations),
        "practice_count": sum(
            o.activity in PRACTICE and o.actor == "student" for o in observations.values()
        ),
        "independent_correct_count": sum(
            o.activity in PRACTICE
            and o.actor == "student"
            and o.correctness == "correct"
            and o.assistance == "none"
            for o in observations.values()
        ),
        "warnings": extraction.warnings + sorted(resolution_warnings),
        "history_basis": "earlier_received_sessions_at_publication",
        "revision": run.revision,
    }
    run.status, run.stage = "completed", "published"
    run.finished_at, run.review_required = now(), review
