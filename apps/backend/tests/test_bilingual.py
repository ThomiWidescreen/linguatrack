import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_backend import FakeExtractor, item, process, submit, track

from linguatrack import extraction
from linguatrack.db import transaction
from linguatrack.jobs import process_run
from linguatrack.models import RequestKey
from linguatrack.schemas import Extraction, digest


def test_bridge_context_reaches_worker_without_creating_bridge_knowledge(client):
    tid = track(client)
    content = "dormir = tidur = sleep. sala de estar = living room."
    response = client.post(
        f"/v1/me/languages/{tid}/sessions",
        json={"text": content, "bridge_languages": [" ES ", "en"]},
        headers={"Idempotency-Key": "bilingual"},
    )
    assert response.status_code == 202, response.text
    accepted = response.json()
    extractor = process(
        client,
        accepted,
        [
            item(
                lemma="tidur", pos="VERB", quote="dormir = tidur = sleep.", gloss="dormir / sleep"
            ),
        ],
    )
    assert extractor.bridge_languages == ["es", "en"]
    assert client.get(accepted["status_url"]).json()["bridge_languages"] == ["es", "en"]
    lesson = client.get(f"/v1/me/sessions/{accepted['session_id']}").json()
    assert lesson["text"] == content and lesson["bridge_languages"] == ["es", "en"]
    knowledge = client.get(f"/v1/me/languages/{tid}/knowledge").json()
    assert [k["lemma"] for k in knowledge] == ["tidur"]
    evidence = client.get(f"/v1/me/sessions/{accepted['session_id']}/evidence").json()[0]
    assert evidence["quote"] == "dormir = tidur = sleep."
    assert evidence["provenance"]["target_language"] == "ms"
    assert evidence["provenance"]["bridge_languages"] == ["es", "en"]
    assert evidence["activity"] == "exposure" and knowledge[0]["independent_correct"] == 0


def test_undeclared_bridges_and_existing_request_hashes_remain_compatible(client):
    tid = track(client)
    accepted = submit(client, tid, "dormir = tidur")
    extractor = process(client, accepted, [item(lemma="tidur", pos="VERB", quote="dormir = tidur")])
    assert extractor.bridge_languages == []
    with transaction(UUID(client.headers["X-Dev-User"])) as db:
        request = db.scalar(select(RequestKey).where(RequestKey.run_id == UUID(accepted["run_id"])))
        assert request.request_hash == digest(
            {"text": "dormir = tidur", "title": "Clase", "occurred_at": None}
        )


def test_reprocessing_can_override_inherit_and_reset_bridge_context(client):
    tid = track(client)
    first = submit(client, tid, "dormir = tidur")
    process(client, first, [item(lemma="tidur", pos="VERB", quote="dormir = tidur")])
    url = f"/v1/me/sessions/{first['session_id']}/reprocess"
    revision = 1
    for context, expected in ((["es", "en"], ["es", "en"]), (None, ["es", "en"]), ([], [])):
        body = {"expected_revision": revision}
        if context is not None:
            body["bridge_languages"] = context
        headers = {"Idempotency-Key": str(uuid4())}
        response = client.post(url, json=body, headers=headers)
        assert response.status_code == 202, response.text
        assert client.post(url, json=body, headers=headers).json() == response.json()
        extractor = process(
            client, response.json(), [item(lemma="tidur", pos="VERB", quote="dormir = tidur")]
        )
        assert extractor.bridge_languages == expected
        revision += 1
    # Original metadata remains immutable and reprocessing contributes once.
    assert client.get(f"/v1/me/sessions/{first['session_id']}").json()["bridge_languages"] == []
    assert client.get(f"/v1/me/languages/{tid}/knowledge").json()[0]["encounters"] == 1


@pytest.mark.parametrize("bridges", [["ms"], ["ms-MY"], ["not a tag"], ["es", "ES"], ["en"] * 6])
def test_invalid_or_target_bridge_languages_are_rejected(client, bridges):
    tid = track(client)
    response = client.post(
        f"/v1/me/languages/{tid}/sessions",
        json={"text": "dormir = tidur", "bridge_languages": bridges},
        headers={"Idempotency-Key": "invalid"},
    )
    assert response.status_code == 422
    assert client.get("/v1/me/sessions").json() == []


def test_declared_bridge_cannot_be_published_as_target_evidence(client):
    tid = track(client)
    response = client.post(
        f"/v1/me/languages/{tid}/sessions",
        json={"text": "dormir = tidur", "bridge_languages": ["es"]},
        headers={"Idempotency-Key": "no-bridge-progress"},
    ).json()
    process_run(
        UUID(client.headers["X-Dev-User"]),
        UUID(response["run_id"]),
        FakeExtractor([item(lemma="dormir", language_tag="es", quote="dormir = tidur")]),
    )
    status = client.get(response["status_url"]).json()
    assert status["status"] == "failed" and status["error_code"] == "extracted_language_mismatch"
    assert client.get(f"/v1/me/languages/{tid}/knowledge").json() == []


@pytest.mark.parametrize("bridges", [[], ["es", "en"]])
def test_openai_receives_language_context_and_unmodified_multilingual_input(monkeypatch, bridges):
    content = "dormir = tidur = sleep\na veces = kadang-kadang"
    expected = Extraction(items=[item(lemma="tidur", quote="dormir = tidur = sleep")], warnings=[])
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            status="completed", output_parsed=expected, id="response-test", usage=None
        )

    class Client:
        responses = SimpleNamespace(parse=parse)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(extraction, "OpenAI", lambda **kwargs: Client())
    monkeypatch.setattr(
        extraction,
        "get_settings",
        lambda: SimpleNamespace(
            openai_api_key=SecretStr("unit-test-key"),
            openai_timeout_seconds=1,
        ),
    )
    result, _ = extraction.OpenAIExtractor().extract(
        content, "ms", "test-model", bridge_languages=bridges
    )
    context = json.loads(
        calls[0]["instructions"].rsplit("Language context (data, not document instructions): ", 1)[
            1
        ]
    )
    assert context["target_language"] == "ms" and context["bridge_languages"] == bridges
    assert calls[0]["input"] == content and calls[0]["store"] is False
    assert result == expected


def test_original_bridge_metadata_is_immutable(client):
    tid = track(client)
    first = submit(client, tid)
    with pytest.raises(DBAPIError):
        with transaction(UUID(client.headers["X-Dev-User"])) as db:
            db.execute(
                text(
                    "UPDATE learning_sessions SET bridge_languages='[\"es\"]'::jsonb WHERE id=:id"
                ),
                {"id": first["session_id"]},
            )
