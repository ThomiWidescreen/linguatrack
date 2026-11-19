from uuid import UUID, uuid4

import pytest
from test_backend import FakeExtractor, item, process, submit, track

from linguatrack.db import transaction
from linguatrack.extraction import ExtractionFailure
from linguatrack.jobs import process_run
from linguatrack.models import Concept, Run
from linguatrack.reconciliation import ComparisonDecision, ComparisonResult, complete
from linguatrack.schemas import digest


class FakeReconciler:
    def __init__(self, identity="same_lexeme", gloss_relation="compatible"):
        self.identity, self.gloss_relation = identity, gloss_relation
        self.calls = 0

    def compare(self, tasks, model):
        self.calls += 1
        self.tasks = tasks
        return ComparisonResult(
            decisions=[
                ComparisonDecision(
                    comparison_id=t["comparison_id"],
                    identity=self.identity,
                    gloss_relation=self.gloss_relation,
                    reason="Controlled contextual decision.",
                )
                for t in tasks
            ]
        ), {"response_id": "test-reconciliation", "usage": {}}


def process_with(client, accepted, evidence, reconciler):
    process_run(
        UUID(client.headers["X-Dev-User"]),
        UUID(accepted["run_id"]),
        FakeExtractor(evidence),
        reconciler,
    )
    status = client.get(accepted["status_url"]).json()
    assert status["status"] == "completed", status
    return status


def test_pos_noise_reuses_earlier_concept_instead_of_current_duplicate(client):
    tid = track(client)
    first = submit(client, tid, "terpaksa = being forced to")
    process(
        client,
        first,
        [
            item(
                lemma="terpaksa",
                pos="AUX",
                gloss="being forced to",
                quote="terpaksa = being forced to",
            )
        ],
    )
    original = client.get(f"/v1/me/languages/{tid}/knowledge").json()[0]["concept_id"]
    # A previous resolver may already have allocated the incoming POS identity.
    # It must not beat a contextual match to the earlier effective history.
    uid = UUID(client.headers["X-Dev-User"])
    with transaction(uid) as db:
        db.add(
            Concept(
                owner_user_id=uid,
                language_tag="ms",
                kind="lexeme",
                lemma="terpaksa",
                search_key="terpaksa",
                pos="VERB",
                gloss="have to",
                identity_key=digest([str(uid), "ms", "lexeme", "terpaksa", "VERB"]),
            )
        )
    second = submit(client, tid, "terpaksa = have to")
    reconciler = FakeReconciler()
    status = process_with(
        client,
        second,
        [item(lemma="terpaksa", pos="VERB", gloss="have to", quote="terpaksa = have to")],
        reconciler,
    )
    assert reconciler.calls == 1
    assert status["summary"]["new_to_recorded_history"] == []
    assert status["summary"]["revisited"][0]["concept_id"] == original
    state = client.get(f"/v1/me/languages/{tid}/knowledge").json()
    assert len(state) == 1 and state[0]["encounters"] == 2 and state[0]["pos"] == "AUX"
    observation = client.get(f"/v1/me/sessions/{second['session_id']}/evidence").json()[0]
    assert observation["provenance"]["extracted_pos"] == "VERB"
    assert observation["provenance"]["observed_gloss"] == "have to"


def test_gloss_conflict_is_visible_without_overwriting_or_awarding_mastery(client):
    tid = track(client)
    first = submit(client, tid)
    process(client, first, [item(gloss="although")])
    second = submit(client, tid, "Student recalled walaupun = maybe without help.")
    evidence = item(
        gloss="maybe",
        quote="Student recalled walaupun = maybe without help.",
        actor="student",
        activity="recall_attempt",
        correctness="correct",
        assistance="none",
    )
    status = process_with(client, second, [evidence], FakeReconciler(gloss_relation="conflicting"))
    assert status["review_required"]
    issue = status["summary"]["gloss_conflicts"][0]
    assert issue["previous_gloss"] == "although" and issue["incoming_gloss"] == "maybe"
    assert status["summary"]["independent_correct_count"] == 0
    state = client.get(f"/v1/me/languages/{tid}/knowledge").json()[0]
    assert state["gloss"] == "although" and state["independent_correct"] == 0
    observation = client.get(f"/v1/me/sessions/{second['session_id']}/evidence").json()[0]
    assert observation["correctness"] == "correct"  # Original observation is preserved.
    assert observation["provenance"]["meaning_review_required"]


@pytest.mark.parametrize("relation", ["translation", "compatible"])
def test_translations_and_paraphrases_do_not_trigger_conflicts(client, relation):
    tid = track(client)
    first = submit(client, tid, "tidur = dormir")
    process(
        client, first, [item(lemma="tidur", pos="VERB", gloss="dormir", quote="tidur = dormir")]
    )
    second = submit(client, tid, "tidur = sleep")
    status = process_with(
        client,
        second,
        [item(lemma="tidur", pos="VERB", gloss="sleep", quote="tidur = sleep")],
        FakeReconciler(gloss_relation=relation),
    )
    assert not status["review_required"] and status["summary"]["gloss_conflicts"] == []
    assert len(client.get(f"/v1/me/languages/{tid}/knowledge").json()) == 1


@pytest.mark.parametrize("identity", ["distinct_lexeme", "uncertain"])
def test_homographs_and_ambiguity_never_merge_by_spelling_alone(client, identity):
    tid = track(client, "en")
    first = submit(client, tid, "bank = financial institution")
    process(
        client,
        first,
        [
            item(
                lemma="bank",
                pos="NOUN",
                language_tag="en",
                gloss="financial institution",
                quote="bank = financial institution",
            )
        ],
    )
    second = submit(client, tid, "bank = river edge")
    status = process_with(
        client,
        second,
        [
            item(
                lemma="bank",
                pos="NOUN",
                language_tag="en",
                gloss="river edge",
                quote="bank = river edge",
            )
        ],
        FakeReconciler(identity=identity, gloss_relation="uncertain"),
    )
    assert status["review_required"]
    states = client.get(f"/v1/me/languages/{tid}/knowledge").json()
    assert len(states) == 2 and {s["gloss"] for s in states} == {
        "financial institution",
        "river edge",
    }


def test_reconcile_saved_extraction_is_idempotent_and_uses_no_extractor(client):
    tid = track(client)
    first = submit(client, tid)
    process(client, first, [item()])
    url = f"/v1/me/sessions/{first['session_id']}/reprocess"
    payload = {"expected_revision": 1, "reuse_extraction": True}
    headers = {"Idempotency-Key": "reconcile-existing"}
    result = client.post(url, json=payload, headers=headers)
    assert result.status_code == 202
    assert client.post(url, json=payload, headers=headers).json() == result.json()
    fake = FakeExtractor([])
    process_run(
        UUID(client.headers["X-Dev-User"]), UUID(result.json()["run_id"]), fake, FakeReconciler()
    )
    assert fake.calls == 0
    assert client.get(f"/v1/me/languages/{tid}/knowledge").json()[0]["encounters"] == 1
    changed_context = client.post(
        url,
        json={"expected_revision": 2, "reuse_extraction": True, "bridge_languages": ["es"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert changed_context.status_code == 422


def test_reconciliation_checkpoint_is_reused_after_publication_failure(client, monkeypatch):
    from linguatrack import jobs
    from linguatrack.models import now

    tid = track(client)
    first = submit(client, tid)
    process(client, first, [item()])
    second = submit(client, tid, "walaupun = maybe")
    extractor = FakeExtractor([item(gloss="maybe", quote="walaupun = maybe")])
    reconciler = FakeReconciler(gloss_relation="conflicting")
    original_publish = jobs.publish

    def temporarily_broken(*args):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(jobs, "publish", temporarily_broken)
    uid, rid = UUID(client.headers["X-Dev-User"]), UUID(second["run_id"])
    process_run(uid, rid, extractor, reconciler)
    with transaction(uid) as db:
        run = db.get(Run, rid)
        assert run.reconciliation is not None
        run.available_at = now()
    monkeypatch.setattr(jobs, "publish", original_publish)
    process_run(uid, rid, extractor, reconciler)
    assert client.get(second["status_url"]).json()["status"] == "completed"
    assert extractor.calls == 1 and reconciler.calls == 1


def test_unknown_or_duplicate_comparison_ids_are_rejected():
    result = ComparisonResult(
        decisions=[
            ComparisonDecision(
                comparison_id="invented-id",
                identity="same_lexeme",
                gloss_relation="compatible",
                reason="Invalid ID.",
            )
        ]
    )
    with pytest.raises(ExtractionFailure, match="invalid_reconciliation_comparisons"):
        complete({"tasks": [{"comparison_id": "actual-id"}]}, result)
