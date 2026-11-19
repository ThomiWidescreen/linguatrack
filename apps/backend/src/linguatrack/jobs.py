import logging
from datetime import timedelta
from uuid import UUID, uuid4

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import Session

from linguatrack.config import get_settings
from linguatrack.db import transaction
from linguatrack.extraction import ExtractionFailure, Extractor, OpenAIExtractor
from linguatrack.models import Lesson, Outbox, Run, Track, now
from linguatrack.schemas import Extraction
from linguatrack.services import enqueue, owned, publish

logger = logging.getLogger(__name__)
broker = RedisBroker(url=get_settings().redis_url)
dramatiq.set_broker(broker)


def classify_error(error):
    if isinstance(error, ExtractionFailure):
        return error.code, error.retryable
    if isinstance(error, (APIConnectionError, APITimeoutError, RateLimitError)):
        return "openai_temporarily_unavailable", True
    if isinstance(error, APIStatusError):
        return f"openai_http_{error.status_code}", error.status_code >= 500
    # Avoid recording raw exception strings: they may contain private text or credentials.
    return "processing_error", True


def process_run(user_id: UUID, run_id: UUID, extractor: Extractor | None = None):
    settings = get_settings()
    token = uuid4()
    with transaction(user_id) as db:
        run = db.scalar(
            select(Run)
            .where(
                Run.id == run_id,
                Run.user_id == user_id,
            )
            .with_for_update()
        )
        if run is None or run.status not in {"queued", "retrying", "running"}:
            return
        if run.status == "running" and run.lease_until and run.lease_until > now():
            return
        if run.available_at > now():
            return
        if run.attempts >= settings.max_attempts:
            run.status, run.error_code, run.finished_at = "failed", "attempts_exhausted", now()
            return
        run.status, run.stage = "running", "extracting" if run.extraction is None else "extracted"
        run.attempts += 1
        run.lease_token = token
        run.lease_until = now() + timedelta(seconds=settings.lease_seconds)
        lesson = owned(db, Lesson, run.session_id, user_id)
        track = owned(db, Track, lesson.track_id, user_id)
        content, language, model = lesson.text, track.language_tag, run.model
        stored = run.extraction
    try:
        if stored is None:
            result, metadata = (extractor or OpenAIExtractor()).extract(content, language, model)
            with transaction(user_id) as db:
                run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
                if run.lease_token != token:
                    return
                run.extraction = result.model_dump(mode="json")
                run.stage = "extracted"
                run.provider_response_id = metadata.get("response_id")
                run.usage = metadata.get("usage", {})
        else:
            Extraction.model_validate(stored)
        with transaction(user_id) as db:
            run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if run.lease_token != token:
                return
            publish(db, run)
            run.lease_until = None
            run.error_code = run.error_code if run.status == "needs_review" else None
    except Exception as error:
        code, retryable = classify_error(error)
        logger.warning("run_failed run_id=%s code=%s type=%s", run_id, code, type(error).__name__)
        with transaction(user_id) as db:
            run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if run.lease_token != token:
                return
            run.error_code, run.lease_until = code, None
            if retryable and run.attempts < settings.max_attempts:
                run.status = "retrying"
                run.available_at = now() + timedelta(seconds=5 * 2 ** (run.attempts - 1))
                enqueue(db, run, f"retry:{run.id}:{run.attempts}")
            else:
                run.status, run.finished_at = "failed", now()


@dramatiq.actor(max_retries=0, time_limit=240000)
def ingest_session(user_id: str, run_id: str):
    # Retry timing and terminal states live in PostgreSQL, not in broker messages.
    process_run(UUID(user_id), UUID(run_id))


def dispatch_once():
    """The local dispatcher is a privileged system process; it never handles lesson text."""
    admin_engine = create_engine(get_settings().migration_database_url, pool_pre_ping=True)
    try:
        with Session(admin_engine) as db, db.begin():
            rows = list(
                db.scalars(
                    select(Outbox)
                    .where(
                        Outbox.published_at.is_(None),
                        Outbox.available_at <= now(),
                    )
                    .order_by(Outbox.available_at)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            )
            for row in rows:
                ingest_session.send(str(row.user_id), str(row.run_id))
                row.published_at = now()
        # Recover lost broker deliveries and dead workers. Stable delivery keys make
        # concurrent dispatchers safe; row locks serialize each run recovery.
        with Session(admin_engine) as db, db.begin():
            runs = list(
                db.scalars(
                    select(Run)
                    .where(
                        or_(
                            (Run.status == "running") & (Run.lease_until < now()),
                            (Run.status.in_(["queued", "retrying"]))
                            & (Run.available_at < now() - timedelta(seconds=30)),
                        )
                    )
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            )
            for run in runs:
                if run.attempts >= get_settings().max_attempts:
                    run.status, run.error_code, run.finished_at = (
                        "failed",
                        "attempts_exhausted",
                        now(),
                    )
                    continue
                pending = db.scalar(
                    select(Outbox.id).where(
                        Outbox.run_id == run.id,
                        Outbox.published_at.is_(None),
                    )
                )
                if pending:
                    continue
                # Move available_at forward to bound redispatch while a queue is busy.
                run.available_at = now()
                enqueue(db, run, f"recover:{run.id}:{uuid4()}")
    finally:
        admin_engine.dispose()
