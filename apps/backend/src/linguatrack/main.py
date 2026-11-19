from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from linguatrack.config import get_settings
from linguatrack.db import engine, transaction
from linguatrack.integrations import capabilities
from linguatrack.models import Concept, Knowledge, Language, Lesson, Observation, Run, Track
from linguatrack.schemas import (
    Accepted,
    CorrectionRequest,
    EvidenceView,
    LanguageView,
    ReprocessRequest,
    RunView,
    SessionCreate,
    SessionDetail,
    SessionView,
    TrackCreate,
    TrackView,
)
from linguatrack.services import DomainError, correct, create_track, owned, reprocess, submit


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()  # Fail at startup if local-only configuration is violated.
    yield


app = FastAPI(
    lifespan=lifespan,
    title="LinguaTrack API",
    version="0.1.0",
    description=(
        "Backend local de aprendizaje de idiomas. **Sin autenticación:** usa un usuario demo "
        "por defecto. X-Dev-User permite simular otros usuarios (no es autenticación). "
        "Solo para desarrollo local.\n\n"
        "1. Crear un track en POST /v1/me/languages (ejemplo: ms). "
        "2. Enviar texto en POST .../{track_id}/sessions con Idempotency-Key. "
        "3. Consultar status_url hasta completed o failed. "
        "4. Ver summary, evidence y knowledge. Nuevas significa nuevas en el historial "
        "registrado; exposición no significa dominio."
    ),
    swagger_ui_parameters={"persistAuthorization": True, "displayRequestDuration": True},
)


@app.exception_handler(DomainError)
async def domain_error_handler(request, error: DomainError):
    return JSONResponse(status_code=error.status, content={"detail": error.detail})


def current_user(
    x_dev_user: Annotated[
        UUID | None, Header(description="Identidad local simulada; no es auth")
    ] = None,
) -> UUID:
    return x_dev_user or get_settings().dev_user_id


UserID = Annotated[UUID, Depends(current_user)]


def database(user_id: UserID):
    with transaction(user_id) as db:
        yield db


DB = Annotated[Session, Depends(database)]
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]
Limit = Annotated[int, Query(ge=1, le=100)]


@app.get("/health/live", tags=["Health"])
def live():
    return {"status": "ok", "environment": get_settings().environment, "authentication": False}


@app.get("/health/ready", tags=["Health"])
def ready():
    try:
        with engine().connect() as connection:
            connection.execute(text("SELECT 1 FROM languages LIMIT 1"))
        with Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1
        ) as redis:
            redis.ping()
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return {"status": "ready"}


@app.get("/v1/me", tags=["Development"])
def me(user_id: UserID):
    return {"user_id": user_id, "authentication": False, "mode": "local_development"}


@app.get("/v1/languages", response_model=list[LanguageView], tags=["Languages"])
def languages(db: DB):
    return list(db.scalars(select(Language).order_by(Language.tag)))


@app.post("/v1/me/languages", response_model=TrackView, status_code=201, tags=["Languages"])
def add_language(body: TrackCreate, user_id: UserID, db: DB):
    return create_track(db, user_id, body.language_tag)


@app.get("/v1/me/languages", response_model=list[TrackView], tags=["Languages"])
def tracks(user_id: UserID, db: DB):
    return list(
        db.scalars(select(Track).where(Track.user_id == user_id).order_by(Track.created_at))
    )


@app.post(
    "/v1/me/languages/{track_id}/sessions",
    response_model=Accepted,
    status_code=202,
    tags=["Sessions"],
    summary="Enviar una clase de texto para procesamiento asíncrono",
)
def submit_session(track_id: UUID, body: SessionCreate, user_id: UserID, db: DB, key: Key):
    return submit(db, user_id, track_id, body, key)


@app.get("/v1/me/sessions", response_model=list[SessionView], tags=["Sessions"])
def sessions(
    user_id: UserID,
    db: DB,
    track_id: UUID | None = None,
    after: UUID | None = None,
    limit: Limit = 50,
):
    query = select(Lesson).where(Lesson.user_id == user_id)
    if track_id:
        owned(db, Track, track_id, user_id)
        query = query.where(Lesson.track_id == track_id)
    if after:
        query = query.where(Lesson.id > after)
    return list(db.scalars(query.order_by(Lesson.id).limit(limit)))


@app.get("/v1/me/sessions/{session_id}", response_model=SessionDetail, tags=["Sessions"])
def session_detail(session_id: UUID, user_id: UserID, db: DB):
    return owned(db, Lesson, session_id, user_id)


@app.get("/v1/me/processing-runs/{run_id}", response_model=RunView, tags=["Processing"])
def run_detail(run_id: UUID, user_id: UserID, db: DB):
    return owned(db, Run, run_id, user_id)


@app.get("/v1/me/sessions/{session_id}/summary", tags=["Sessions"])
def summary(session_id: UUID, user_id: UserID, db: DB):
    lesson = owned(db, Lesson, session_id, user_id)
    if lesson.published_run_id is None:
        raise DomainError(409, "Session has no published result yet; consult processing status")
    run = owned(db, Run, lesson.published_run_id, user_id)
    return {"run_id": run.id, "review_required": run.review_required, **run.summary}


@app.get(
    "/v1/me/sessions/{session_id}/evidence",
    response_model=list[EvidenceView],
    tags=["Evidence"],
)
def session_evidence(
    session_id: UUID, user_id: UserID, db: DB, after: UUID | None = None, limit: Limit = 50
):
    lesson = owned(db, Lesson, session_id, user_id)
    query = select(Observation).where(
        Observation.user_id == user_id,
        Observation.run_id == lesson.published_run_id,
    )
    if after:
        query = query.where(Observation.id > after)
    return list(db.scalars(query.order_by(Observation.id).limit(limit)))


@app.post(
    "/v1/me/sessions/{session_id}/reprocess",
    response_model=Accepted,
    status_code=202,
    tags=["Processing"],
)
def retry_session(session_id: UUID, body: ReprocessRequest, user_id: UserID, db: DB, key: Key):
    return reprocess(db, user_id, session_id, body, key)


@app.post(
    "/v1/me/sessions/{session_id}/corrections",
    response_model=Accepted,
    status_code=202,
    tags=["Evidence"],
)
def correct_session(session_id: UUID, body: CorrectionRequest, user_id: UserID, db: DB, key: Key):
    return correct(db, user_id, session_id, body, key)


@app.get("/v1/me/languages/{track_id}/knowledge", tags=["Knowledge"])
def knowledge(
    track_id: UUID, user_id: UserID, db: DB, after: UUID | None = None, limit: Limit = 50
):
    owned(db, Track, track_id, user_id)
    query = (
        select(Knowledge, Concept)
        .join(Concept, Concept.id == Knowledge.concept_id)
        .where(
            Knowledge.user_id == user_id,
            Knowledge.track_id == track_id,
        )
    )
    if after:
        query = query.where(Knowledge.id > after)
    rows = db.execute(query.order_by(Knowledge.id).limit(limit)).all()
    return [
        {
            "id": k.id,
            "concept_id": c.id,
            "lemma": c.lemma,
            "kind": c.kind,
            "pos": c.pos,
            "gloss": c.gloss,
            "reference_status": c.status,
            "dimension": k.dimension,
            "state": k.state,
            "encounters": k.encounters,
            "practice": k.practice,
            "independent_correct": k.independent_correct,
            "assisted_correct": k.assisted_correct,
            "incorrect": k.incorrect,
            "contradictory_evidence": k.incorrect > 0 and k.independent_correct > 0,
            "first_seen": k.first_seen,
            "last_seen": k.last_seen,
            "mastery_probability": None,
            "projector_version": k.projector_version,
        }
        for k, c in rows
    ]


@app.get("/v1/me/languages/{track_id}/progress", tags=["Knowledge"])
def progress(track_id: UUID, user_id: UserID, db: DB):
    owned(db, Track, track_id, user_id)
    return {
        "encountered_lexemes": db.scalar(
            select(func.count(func.distinct(Knowledge.concept_id)))
            .join(
                Concept,
                Knowledge.concept_id == Concept.id,
            )
            .where(
                Knowledge.user_id == user_id,
                Knowledge.track_id == track_id,
                Concept.kind == "lexeme",
            )
        ),
        "demonstrated_concepts": db.scalar(
            select(func.count(func.distinct(Knowledge.concept_id))).where(
                Knowledge.user_id == user_id,
                Knowledge.track_id == track_id,
                Knowledge.independent_correct > 0,
            )
        ),
        "cefr_estimate": None,
        "mastery_percentage": None,
        "meaning": "Recorded evidence only; missing evidence means unknown, not lack of knowledge.",
    }


@app.get(
    "/v1/me/knowledge/{concept_id}/evidence", response_model=list[EvidenceView], tags=["Evidence"]
)
def concept_evidence(
    concept_id: UUID,
    user_id: UserID,
    db: DB,
    after: UUID | None = None,
    limit: Limit = 50,
):
    query = (
        select(Observation)
        .join(Lesson, Lesson.published_run_id == Observation.run_id)
        .where(
            Observation.user_id == user_id,
            Observation.concept_id == concept_id,
        )
    )
    if not db.scalar(
        select(Knowledge.id).where(Knowledge.user_id == user_id, Knowledge.concept_id == concept_id)
    ):
        raise DomainError(404, "Resource not found")
    if after:
        query = query.where(Observation.id > after)
    return list(db.scalars(query.order_by(Observation.id).limit(limit)))


@app.get("/v1/integrations/capabilities", tags=["Integrations"])
def integration_capabilities():
    return capabilities()
