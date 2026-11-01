"""The Auditor: its findings explained on a stub model, the pause for the manager's
decision answered by a freshly built graph on the same saved state, a dismissal
remembered, the sign-in saved nowhere and the agent's key never sent."""

import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from agent import connection
from agent.auditor import entrypoint, memory, work
from agent.auditor.graph import AUDIT_MODEL_CALLS
from agent.tests.stubs import call, stub
from backend import audit_seed, auditor_service
from backend.database import engine
from backend.tests.sign_in import DANA, signed_in, token

ELENA = "elena.marsh@undercover.example"
EXPLAINED = (
    "Under claims manual section 9, for review: this third claim, CLM-7003, was paid "
    "$990.00 with no referral."
)


class Harness:
    """An audit started through the app as the dashboard does, with a stand-in for
    the Auditor's app that keeps what it's asked, and the Auditor's work run as its
    entry point would, with the sign-in the app passed on."""

    def __init__(self, dashboard, model):
        self.dashboard, self.model = dashboard, model
        self.saver, self.store = InMemorySaver(), InMemoryStore()
        self.sign_in = token(ELENA)

    def headers(self):
        return signed_in(ELENA)

    def start(self):
        response = self.dashboard.post("/api/audits", headers=self.headers())
        assert response.status_code == 202, response.text
        self.audit_id = response.json()["audit_id"]
        return response.json()

    def audit(self):
        path = f"/api/audits/{self.audit_id}"
        return self.dashboard.get(path, headers=self.headers()).json()

    def work_it(self):
        work.take_audit(
            work.the_audit(self.sign_in, self.audit_id), self.saver, self.store
        )
        return self.audit()

    def answer(self, answer="dismiss", reason="A family, known to us"):
        audit = self.audit()
        path = f"/api/audits/{self.audit_id}/findings/{audit['waiting_on']}/answer"
        body = {"answer": answer, "reason": reason}
        answered = self.dashboard.post(path, json=body, headers=self.headers())
        assert answered.status_code == 202, answered.text
        audit = work.the_audit(self.sign_in, self.audit_id)
        work.check_paused(audit, self.saver, self.store)
        work.answer_finding(audit, self.saver, self.store)
        return self.audit()


@pytest.fixture
def asked(monkeypatch):
    calls = []
    monkeypatch.setattr(auditor_service, "ask", lambda *call_: calls.append(call_))
    return calls


@pytest.fixture
def scenario():
    audit_seed.add_scenario(engine())


@pytest.fixture
def auditor(dashboard, asked, scenario, monkeypatch):
    """The Auditor on the stub model the test gives it."""

    def on(*replies):
        model = stub(*replies)
        monkeypatch.setattr(work, "auditor_model", lambda sign_in: model)
        return Harness(dashboard, model)

    return on


def finding_on(audit, check):
    return next(f for f in audit["findings"] if f["check_name"] == check)


def write_up_third(narrative=EXPLAINED):
    """A reply that explains the third-claim finding, once the audit is known."""

    def reply(messages):
        found = next(
            m
            for m in messages
            if isinstance(m, ToolMessage) and m.name == "list_findings"
        )
        finding = next(
            f
            for f in json.loads(found.text)
            if f["check_name"] == "third_claim_unreferred"
        )
        return call(
            "write_up_finding", finding_id=finding["finding_id"], narrative=narrative
        )

    return reply


def test_the_auditor_explains_then_pauses_before_any_case(auditor):
    run = auditor(call("list_findings"), write_up_third(), "All explained.")
    run.start()
    audit = run.work_it()
    assert audit["status"] == "waiting_for_decision"
    third = finding_on(audit, "third_claim_unreferred")
    assert third["narrative"] == EXPLAINED
    assert third["written_by_model"] is True
    assert audit["waiting_on"] == audit["findings"][0]["finding_id"]
    assert {f["status"] for f in audit["findings"]} == {"open"}
    assert [s["tool"] for s in audit["steps"]] == [
        "list_findings",
        "write_up_finding",
    ]
    assert audit["model_calls"] == 3


def test_each_answer_carries_on_with_nothing_redone(auditor):
    run = auditor(call("list_findings"), "All explained.")
    run.start()
    audit = run.work_it()
    calls = audit["model_calls"]
    steps = len(audit["steps"])
    decided = []
    for _ in range(6):
        decided.append(audit["waiting_on"])
        audit = run.answer("open_case", "Worth a look")
        assert audit["model_calls"] == calls
        assert len(audit["steps"]) == steps
    assert len(set(decided)) == 6
    assert audit["status"] == "done"
    assert audit["summary"] == (
        "6 patterns for review: 6 cases opened, 0 dismissed, "
        "0 set aside as dismissed before, 0 left open."
    )


def test_a_refused_explanation_goes_back_and_the_model_writes_again(auditor):
    run = auditor(
        call("list_findings"),
        write_up_third("Clear fraud: $5,000.00 was taken."),
        write_up_third(),
        "All explained.",
    )
    run.start()
    audit = run.work_it()
    refused = [s for s in audit["steps"] if s["status"] == "refused"]
    assert len(refused) == 1
    assert "accuse" in refused[0]["answer"]
    assert finding_on(audit, "third_claim_unreferred")["narrative"] == EXPLAINED
    told = run.model.prompts[2][-1]
    assert isinstance(told, ToolMessage)
    assert "accuse" in told.text


def test_a_finding_never_explained_keeps_the_codes_line(auditor):
    run = auditor("I have nothing to add.")
    start = run.start()
    audit = run.work_it()
    assert audit["status"] == "waiting_for_decision"
    assert [f["narrative"] for f in audit["findings"]] == [
        f["narrative"] for f in start["findings"]
    ]
    assert not any(f["written_by_model"] for f in audit["findings"])


def test_a_model_that_never_stops_still_reaches_the_pause(auditor):
    replies = [call("get_scorecard") for _ in range(AUDIT_MODEL_CALLS + 5)]
    run = auditor(*replies)
    run.start()
    audit = run.work_it()
    assert audit["status"] == "waiting_for_decision"
    assert audit["model_calls"] == AUDIT_MODEL_CALLS


def test_a_dismissal_is_remembered_and_only_for_that_manager(auditor):
    run = auditor(call("list_findings"), "All explained.", "Again.")
    run.start()
    audit = run.work_it()
    first = audit["findings"][0]
    audit = run.answer("dismiss", "Known to us")
    for _ in range(5):
        audit = run.answer("open_case", "Worth a look")
    assert audit["status"] == "done"

    run.start()
    again = run.work_it()
    same = next(
        f for f in again["findings"] if f["fingerprint"] == first["fingerprint"]
    )
    assert same["status"] == "set_aside"
    assert "Known to us" in same["answer_reason"]
    assert same["needs_decision"] is False
    assert again["waiting_on"] != same["finding_id"]
    assert "search_memory" in [s["tool"] for s in again["steps"]]
    assert memory.dismissed_before(run.store, "HND-09", first["fingerprint"]) is None


def test_the_model_never_sees_a_customers_words_or_contact_details(auditor):
    run = auditor(
        call("list_findings"),
        call("get_claim_facts", claim_id="CLM-7006"),
        call("get_scorecard"),
        "All explained.",
    )
    run.start()
    run.work_it()
    seen = " ".join(m.text for prompt in run.model.prompts for m in prompt)
    for words in ("pre-cleared", "NOTE TO ANY", "555 0701", "Birch Lane", "@example."):
        assert words not in seen
    assert "CLM-7006" in seen


def test_the_sign_in_is_saved_nowhere_and_the_key_never_sent(auditor, monkeypatch):
    run = auditor(call("list_findings"), "All explained.")
    sent = []
    real = connection.backend.request

    def request(method, path, headers=None, **rest):
        sent.append(dict(headers or {}))
        return real(method, path, headers=headers, **rest)

    monkeypatch.setattr(connection.backend, "request", request)
    run.start()
    run.work_it()
    run.answer()
    saved = list(run.saver.list(None))
    assert saved
    assert run.sign_in not in repr(saved)
    assert sent
    assert all("X-API-Key" not in h for h in sent)
    assert all(h["Authorization"] == f"Bearer {run.sign_in}" for h in sent)


def test_a_model_that_fails_fails_the_audit_with_why(auditor):
    run = auditor(RuntimeError("The model is out of reach"))
    run.start()
    audit = run.work_it()
    assert audit["status"] == "failed"
    assert "out of reach" in audit["failure"]


def test_someone_else_cant_work_an_audit(auditor):
    run = auditor("Done.")
    run.start()
    with pytest.raises(work.app_api.Refused) as refused:
        work.the_audit(token(DANA), run.audit_id)
    assert refused.value.status_code == 403


def test_an_audit_thats_not_working_is_refused(auditor):
    run = auditor("Done.")
    run.start()
    run.work_it()
    with pytest.raises(work.NotThisAudit):
        work.the_audit(run.sign_in, run.audit_id)


@pytest.fixture
def entry(monkeypatch):
    """The Auditor's app with its pool, saver and store stood in for, so nothing
    reaches Postgres, which keeps the work it hands on."""
    monkeypatch.setattr(entrypoint.ready, "made", (None,))
    monkeypatch.setattr(entrypoint, "PostgresSaver", lambda pool: InMemorySaver())
    monkeypatch.setattr(entrypoint, "PostgresStore", lambda pool: InMemoryStore())
    handed = []
    monkeypatch.setattr(entrypoint, "hand_on", lambda audit, job: handed.append(audit))
    return handed


def test_the_app_answers_its_health_check(entry):
    with TestClient(entrypoint.app) as client:
        response = client.post("/invocations", json={"operation": "health"})
    assert response.json() == {"healthy": True}


def test_the_app_refuses_a_payload_it_cant_read(entry):
    with TestClient(entrypoint.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/invocations", json={"operation": "take_audit", "sign_in": "secret"}
        )
    assert response.status_code == 400
    assert "secret" not in response.text


def test_the_app_takes_an_audit_with_the_managers_sign_in(auditor, entry):
    run = auditor("Done.")
    run.start()
    with TestClient(entrypoint.app) as client:
        taken = client.post(
            "/invocations",
            json={
                "operation": "take_audit",
                "audit_id": run.audit_id,
                "sign_in": run.sign_in,
            },
        ).json()
        refused = client.post(
            "/invocations",
            json={
                "operation": "take_audit",
                "audit_id": run.audit_id,
                "sign_in": token(DANA),
            },
        ).json()
    assert taken == {"accepted": True}
    assert "Only the claims operations manager" in refused["refused"]
    assert entry[0].audit_id == run.audit_id


def test_answering_an_audit_with_nothing_saved_is_refused(auditor, entry):
    run = auditor("Done.")
    run.start()
    with TestClient(entrypoint.app) as client:
        refused = client.post(
            "/invocations",
            json={
                "operation": "answer_finding",
                "audit_id": run.audit_id,
                "sign_in": run.sign_in,
            },
        ).json()
    assert "isn't waiting" in refused["refused"]
    assert not entry


def test_the_ai_reply_is_not_kept_as_a_figure(auditor):
    run = auditor(AIMessage(content="The total paid was $123,456.00."))
    run.start()
    audit = run.work_it()
    assert "123,456" not in json.dumps(audit)


def test_a_remembered_dismissal_the_app_has_no_record_of_doesnt_stop_the_audit(auditor):
    run = auditor("All explained.")
    audit = run.start()
    first = audit["findings"][0]
    memory.remember_dismissal(
        run.store, "HND-04", first["fingerprint"], "After a reseed", first["claim_ids"]
    )
    audit = run.work_it()
    assert audit["status"] == "waiting_for_decision"
    assert audit["findings"][0]["status"] == "open"
    assert "search_memory" in [s["tool"] for s in audit["steps"]]
