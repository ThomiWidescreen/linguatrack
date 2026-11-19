import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from linguatrack.config import ROOT, Settings, get_settings
from linguatrack.db import transaction
from linguatrack.extraction import ExtractionFailure, span_for
from linguatrack.integrations import ADAPTERS
from linguatrack.jobs import dispatch_once, process_run
from linguatrack.models import Knowledge, Lesson, Observation, Outbox, Run, now
from linguatrack.reference import import_build
from linguatrack.schemas import ExtractedEvidence, Extraction
from linguatrack.services import advisory_lock, rebuild_knowledge


def item(lemma="walaupun", quote="We learned walaupun.", **kwargs):
    return ExtractedEvidence(
        **{
            "lemma": lemma,
            "kind": "lexeme",
            "pos": "SCONJ",
            "gloss": "although",
            "language_tag": "ms",
            "quote": quote,
            "quote_occurrence": 0,
            "activity": "exposure",
            "correctness": "unknown",
            "assistance": "unknown",
            "actor": "unknown",
            "dimension": "unspecified",
            "confidence": 0.9,
            **kwargs,
        }
    )


class FakeExtractor:
    def __init__(self, items):
        self.result = Extraction(items=items, warnings=[])
        self.calls = 0

    def extract(self, content, language, model):
        self.calls += 1
        return self.result, {"response_id": "test-response", "usage": {}}


def track(client, language="ms"):
    result = client.post("/v1/me/languages", json={"language_tag": language})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def submit(client, track_id, content="We learned walaupun.", key=None):
    result = client.post(
        f"/v1/me/languages/{track_id}/sessions",
        json={"text": content},
        headers={"Idempotency-Key": key or str(uuid4())},
    )
    assert result.status_code == 202, result.text
    return result.json()


def process(client, response, items):
    extractor = FakeExtractor(items)
    process_run(UUID(client.headers["X-Dev-User"]), UUID(response["run_id"]), extractor)
    status = client.get(response["status_url"]).json()
    assert status["status"] == "completed", status
    return extractor


def test_swagger_openapi_and_integrations(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    schema = client.get("/openapi.json").json()
    assert "SessionCreate" in schema["components"]["schemas"]
    assert client.get("/v1/me").json()["authentication"] is False
    providers = client.get("/v1/integrations/capabilities").json()
    assert [p["provider"] for p in providers if p["enabled"]] == ["manual"]
    with pytest.raises(NotImplementedError):
        ADAPTERS["zoom"].normalize({})


def test_languages_validation_and_duplicate(client):
    assert len(client.get("/v1/languages").json()) == 6
    track(client)
    assert client.post("/v1/me/languages", json={"language_tag": "ms"}).status_code == 409
    assert client.post("/v1/me/languages", json={"language_tag": "bogus"}).status_code == 422


def test_idempotency_and_input_validation(client):
    tid = track(client)
    first = submit(client, tid, key="class-1")
    assert submit(client, tid, key="class-1") == first
    conflict = client.post(
        f"/v1/me/languages/{tid}/sessions",
        json={"text": "Different class"},
        headers={"Idempotency-Key": "class-1"},
    )
    assert conflict.status_code == 409
    assert client.post(f"/v1/me/languages/{tid}/sessions", json={"text": "  "}).status_code == 422
    oversized = client.post(
        f"/v1/me/languages/{tid}/sessions",
        json={"text": "x" * 40001},
        headers={"Idempotency-Key": "too-large"},
    )
    assert oversized.status_code == 413
    assert client.get(f"/v1/me/sessions/{first['session_id']}/summary").status_code == 409


def test_two_lessons_exposure_is_not_mastery_and_redelivery_is_safe(client):
    tid = track(client)
    first = submit(client, tid)
    extractor = process(client, first, [item()])
    process_run(UUID(client.headers["X-Dev-User"]), UUID(first["run_id"]), extractor)
    assert extractor.calls == 1
    state = client.get(f"/v1/me/languages/{tid}/knowledge").json()[0]
    assert state["state"] == "encountered"
    assert state["independent_correct"] == 0 and state["mastery_probability"] is None
    second_text = "The student used walaupun correctly without assistance. We introduced meskipun."
    second = submit(client, tid, second_text)
    process(
        client,
        second,
        [
            item(
                quote="The student used walaupun correctly without assistance.",
                actor="student",
                activity="production_attempt",
                correctness="correct",
                assistance="none",
            ),
            item(lemma="meskipun", quote="We introduced meskipun."),
        ],
    )
    summary = client.get(f"/v1/me/sessions/{second['session_id']}/summary").json()
    assert [c["lemma"] for c in summary["new_to_recorded_history"]] == ["meskipun"]
    assert [c["lemma"] for c in summary["revisited"]] == ["walaupun"]
    states = {s["lemma"]: s for s in client.get(f"/v1/me/languages/{tid}/knowledge").json()}
    assert states["walaupun"]["encounters"] == 2
    assert states["walaupun"]["independent_correct"] == 1
    assert states["meskipun"]["state"] == "encountered"
    assert client.get(f"/v1/me/languages/{tid}/progress").json()["encountered_lexemes"] == 2
    uid = UUID(client.headers["X-Dev-User"])

    def snapshot():
        with transaction(uid) as db:
            return sorted(
                (str(k.concept_id), k.encounters, k.independent_correct)
                for k in db.scalars(
                    select(Knowledge).where(Knowledge.track_id == UUID(tid)),
                )
            )

    before = snapshot()
    with transaction(uid) as db:
        advisory_lock(db, f"track:{tid}")
        rebuild_knowledge(db, uid, UUID(tid))
    assert snapshot() == before


def test_teacher_and_unknown_assistance_cannot_demonstrate(client):
    tid = track(client)
    content = "Teacher used walaupun. Student recalled meskipun."
    accepted = submit(client, tid, content)
    process(
        client,
        accepted,
        [
            item(
                quote="Teacher used walaupun.",
                actor="teacher",
                activity="production_attempt",
                correctness="correct",
                assistance="none",
            ),
            item(
                lemma="meskipun",
                quote="Student recalled meskipun.",
                actor="student",
                activity="recall_attempt",
                correctness="correct",
                assistance="unknown",
            ),
        ],
    )
    rows = client.get(f"/v1/me/languages/{tid}/knowledge").json()
    assert all(r["independent_correct"] == 0 for r in rows)
    assert {r["lemma"]: r["practice"] for r in rows} == {"walaupun": 0, "meskipun": 1}


def test_correction_and_reprocess_replace_effective_evidence(client):
    tid = track(client)
    first = submit(client, tid)
    evidence = item(
        actor="student", activity="recall_attempt", correctness="correct", assistance="none"
    )
    process(client, first, [evidence])
    observation = client.get(f"/v1/me/sessions/{first['session_id']}/evidence").json()[0]
    url = f"/v1/me/sessions/{first['session_id']}/corrections"
    body = {
        "expected_revision": 1,
        "observation_id": observation["id"],
        "correctness": "incorrect",
        "reason": "Teacher note was wrong",
    }
    corrected = client.post(url, json=body, headers={"Idempotency-Key": "correct-1"})
    assert corrected.status_code == 202, corrected.text
    assert (
        client.post(url, json=body, headers={"Idempotency-Key": "correct-1"}).json()
        == corrected.json()
    )
    process(client, corrected.json(), [])  # Stored extraction reused, not fake output.
    states = client.get(f"/v1/me/languages/{tid}/knowledge").json()
    assert states[0]["independent_correct"] == 0 and states[0]["incorrect"] == 1
    reprocessed = client.post(
        f"/v1/me/sessions/{first['session_id']}/reprocess",
        json={"expected_revision": 2},
        headers={"Idempotency-Key": "reprocess-1"},
    )
    process(client, reprocessed.json(), [evidence])
    states = client.get(f"/v1/me/languages/{tid}/knowledge").json()
    assert states[0]["encounters"] == 1 and states[0]["incorrect"] == 1
    uid = UUID(client.headers["X-Dev-User"])
    with transaction(uid) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(Observation).where(Observation.user_id == uid)
            )
            == 3
        )


def test_changed_correction_anchor_does_not_overwrite_publication(client):
    tid = track(client)
    first = submit(client, tid)
    process(client, first, [item()])
    observation = client.get(f"/v1/me/sessions/{first['session_id']}/evidence").json()[0]
    correction = client.post(
        f"/v1/me/sessions/{first['session_id']}/corrections",
        json={
            "expected_revision": 1,
            "observation_id": observation["id"],
            "discard": True,
            "reason": "Not studied",
        },
        headers={"Idempotency-Key": "discard"},
    ).json()
    process(client, correction, [])
    reprocessed = client.post(
        f"/v1/me/sessions/{first['session_id']}/reprocess",
        json={"expected_revision": 2},
        headers={"Idempotency-Key": "reextract"},
    ).json()
    process_run(UUID(client.headers["X-Dev-User"]), UUID(reprocessed["run_id"]), FakeExtractor([]))
    assert client.get(reprocessed["status_url"]).json()["status"] == "needs_review"
    lesson = client.get(f"/v1/me/sessions/{first['session_id']}").json()
    assert lesson["published_run_id"] == correction["run_id"]


def test_invalid_span_fails_atomically(client):
    tid = track(client)
    response = submit(client, tid)
    process_run(
        UUID(client.headers["X-Dev-User"]),
        UUID(response["run_id"]),
        FakeExtractor(
            [
                item(),
                item(lemma="made-up", quote="This was not in the source"),
            ]
        ),
    )
    status = client.get(response["status_url"]).json()
    assert status["status"] == "failed" and status["error_code"] == "unsupported_evidence_span"
    assert client.get(f"/v1/me/languages/{tid}/knowledge").json() == []


def test_isolation_api_and_rls(client):
    tid = track(client)
    response = submit(client, tid)
    process(client, response, [item()])
    other = uuid4()
    assert client.get(response["status_url"], headers={"X-Dev-User": str(other)}).status_code == 404
    assert (
        client.get(
            f"/v1/me/languages/{tid}/knowledge", headers={"X-Dev-User": str(other)}
        ).status_code
        == 404
    )
    with transaction(other) as db:
        assert db.get(Lesson, UUID(response["session_id"])) is None
        assert not list(db.scalars(select(Observation)))
        assert not list(db.scalars(select(Knowledge)))


def test_immutable_evidence_role(client):
    tid = track(client)
    first = submit(client, tid)
    process(client, first, [item()])
    with pytest.raises(DBAPIError):
        with transaction(UUID(client.headers["X-Dev-User"])) as db:
            db.execute(text("DELETE FROM learning_observations"))


def test_duplicate_activities_not_double_counted(client):
    tid = track(client)
    first = submit(client, tid)
    process(
        client,
        first,
        [
            item(
                actor="student", activity="recall_attempt", correctness="correct", assistance="none"
            ),
            item(actor="student", activity="review"),
        ],
    )
    state = client.get(f"/v1/me/languages/{tid}/knowledge").json()[0]
    assert state["encounters"] == 1 and state["practice"] == 1


def test_conjunction_tags_and_bare_construction_labels_do_not_duplicate_vocabulary(client):
    tid = track(client)
    first = submit(client, tid)
    process(client, first, [item(pos="CCONJ")])
    second = submit(client, tid)
    process(client, second, [item(pos="SCONJ", kind="construction")])
    state = client.get(f"/v1/me/languages/{tid}/knowledge").json()
    assert len(state) == 1 and state[0]["encounters"] == 2 and state[0]["kind"] == "lexeme"
    summary = client.get(f"/v1/me/sessions/{second['session_id']}/summary").json()
    assert len(summary["revisited"]) == 1 and summary["new_to_recorded_history"] == []
    assert summary["review_required"] is True


def test_outbox_survives_broker_failure(client, monkeypatch):
    from linguatrack import jobs

    tid = track(client)
    response = submit(client, tid)

    def unavailable(*args):
        raise ConnectionError("test")

    monkeypatch.setattr(jobs.ingest_session, "send", unavailable)
    with pytest.raises(ConnectionError):
        dispatch_once()
    with transaction(UUID(client.headers["X-Dev-User"])) as db:
        delivery = db.scalar(select(Outbox).where(Outbox.run_id == UUID(response["run_id"])))
        assert delivery.published_at is None


def test_retry_and_stale_lease_recovery(client):
    tid = track(client)
    response = submit(client, tid)
    uid, rid = UUID(client.headers["X-Dev-User"]), UUID(response["run_id"])

    class TemporarilyBroken:
        def extract(self, *args):
            raise ExtractionFailure("temporary_test", retryable=True)

    process_run(uid, rid, TemporarilyBroken())
    assert client.get(response["status_url"]).json()["status"] == "retrying"
    with transaction(uid) as db:
        run = db.get(Run, rid)
        run.status = "running"
        run.lease_until = now() - timedelta(seconds=1)
        run.available_at = now() - timedelta(seconds=1)
    process(client, response, [item()])
    assert client.get(response["status_url"]).json()["attempts"] == 2


def test_concurrent_submissions_and_publications_do_not_duplicate_or_lose_progress(client):
    tid = track(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(client, tid, key="concurrent"), range(2)))
    assert results[0] == results[1]
    another = submit(client, tid, key="another-activity")
    uid = UUID(client.headers["X-Dev-User"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(
                lambda result: process_run(uid, UUID(result["run_id"]), FakeExtractor([item()])),
                [results[0], another],
            )
        )
    states = client.get(f"/v1/me/languages/{tid}/knowledge").json()
    assert len(states) == 1 and states[0]["encounters"] == 2


def test_stale_run_cannot_publish_over_new_revision(client):
    tid = track(client)
    first = submit(client, tid)

    class SupersedingExtractor(FakeExtractor):
        def extract(self, *args):
            result = client.post(
                f"/v1/me/sessions/{first['session_id']}/reprocess",
                json={"expected_revision": 1},
                headers={"Idempotency-Key": "newer"},
            )
            assert result.status_code == 202
            return super().extract(*args)

    process_run(
        UUID(client.headers["X-Dev-User"]),
        UUID(first["run_id"]),
        SupersedingExtractor([item()]),
    )
    assert client.get(first["status_url"]).json()["status"] == "superseded"
    assert client.get(f"/v1/me/languages/{tid}/knowledge").json() == []


def test_reference_import_integrity_idempotence_and_provenance(tmp_path):
    source = ROOT / "packages/lexicon/examples/output"
    first = import_build(source)
    assert import_build(source)["already_imported"] is True
    admin = create_engine(get_settings().migration_database_url)
    with Session(admin) as db:
        count = db.scalar(
            text("SELECT count(*) FROM reference_assertions WHERE build_id=:id"),
            {"id": first["build_id"]},
        )
        assert count == sum(json.loads((source / "manifest.json").read_text())["counts"].values())
    admin.dispose()
    import shutil

    shutil.copytree(source, tmp_path / "broken")
    (tmp_path / "broken/entries.jsonl").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        import_build(tmp_path / "broken")


def test_spans_unicode_and_production_guard():
    assert span_for("é 你好 é", "é", 1) == (5, 6)
    assert span_for("Only one quote.", "one quote", 9) == (5, 14)
    with pytest.raises(ExtractionFailure):
        span_for("abc", "not here", 0)
    with pytest.raises(ValidationError, match="Authentication"):
        Settings(environment="production")
