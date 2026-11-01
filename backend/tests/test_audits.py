"""The Auditor's checks and routes: the planted patterns found and the decoys left
alone, only the manager let in, nothing that could instruct the Auditor or identify
how to reach a customer given out, and an explanation checked in code."""

import json
from dataclasses import replace

import pytest
from sqlalchemy import insert, select, update

from backend import audit_seed, audit_writeups, auditor_service, audits
from backend.audit_checks import Ledger, LedgerClaim, links_between, run_checks
from backend.database import audits as audits_table
from backend.database import engine, load, sent_back_decisions
from backend.dependencies import API_KEY_HEADER
from backend.runtime_calls import NotTaken
from backend.tests.sign_in import DANA, signed_in

ELENA = "elena.marsh@undercover.example"
JONAH = "jonah.albright@undercover.example"
PLANTED = load("audit/planted.json")


@pytest.fixture
def asked(monkeypatch):
    """Keep what the app asks the Auditor to do."""
    calls = []
    monkeypatch.setattr(auditor_service, "ask", lambda *call: calls.append(call))
    return calls


@pytest.fixture
def scenario():
    audit_seed.add_scenario(engine())


def manager(client, method, path, **request):
    return client.request(method, path, headers=signed_in(ELENA), **request)


def started(client, asked):
    response = manager(client, "POST", "/api/audits")
    assert response.status_code == 202, response.text
    return response.json()


def waiting_on(client, audit, finding_id):
    response = manager(
        client,
        "POST",
        f"/api/audits/{audit['audit_id']}/pause",
        json={"finding_id": finding_id, "model_calls": 1, "cost": 0.01},
    )
    assert response.status_code == 200, response.text


def drafts():
    with engine().connect() as db:
        return run_checks(audits.ledger_of(db))


def test_the_checks_find_every_planted_pattern_and_no_decoy(scenario):
    found = drafts()
    prints = {d.fingerprint for d in found}
    assert set(PLANTED["planted"]) <= prints
    for draft in found:
        for decoy in PLANTED["decoy_customers"] + PLANTED["decoy_handlers"]:
            assert decoy not in draft.fingerprint
    assert prints == set(PLANTED["planted"])


def test_one_payout_just_under_the_limit_is_no_pattern(scenario):
    assert not [d for d in drafts() if "CLM-7106" in d.claim_ids]


def test_a_family_at_one_address_is_no_pattern(scenario):
    assert not [d for d in drafts() if "CUS-7101" in d.subject]


def test_a_third_claim_rightly_referred_is_no_pattern(scenario):
    third = [d for d in drafts() if d.check == "third_claim_unreferred"]
    assert [d.subject for d in third] == ["CLM-7003"]


def test_an_unseeded_queue_has_no_findings():
    assert drafts() == []


def test_every_figure_of_a_finding_comes_from_the_records(scenario):
    send_backs = next(d for d in drafts() if d.check == "send_back_raises")
    assert send_backs.evidence["raises"] == 2
    assert send_backs.evidence["added"] == (1180 - 720) + (1240 - 640)
    assert send_backs.exposure == 1180 + 1240
    linked = next(d for d in drafts() if d.check == "linked_claimants")
    assert linked.evidence["approvals"] == 9
    assert sorted(linked.evidence["link_kinds"]) == [
        "shared_address",
        "shared_phone",
        "shared_traveler",
    ]


@pytest.mark.parametrize("email", [DANA, JONAH])
def test_only_the_manager_can_audit(client, scenario, asked, email):
    for method, path in (
        ("POST", "/api/audits"),
        ("GET", "/api/audits"),
        ("GET", "/api/audit-scorecard"),
        ("GET", "/api/audit-claims/CLM-7005"),
    ):
        refused = client.request(method, path, headers=signed_in(email))
        assert refused.status_code == 403
        assert "Only the claims operations manager" in refused.json()["detail"]
    assert asked == []


def test_the_agents_key_is_refused(client, scenario, agent_key):
    headers = signed_in(ELENA) | {API_KEY_HEADER: agent_key}
    assert client.get("/api/audits", headers=headers).status_code == 403


def test_nothing_the_auditor_reads_holds_a_customers_words_or_contact_details(
    client, scenario, asked
):
    audit = started(client, asked)
    seen = json.dumps(
        [
            manager(client, "GET", f"/api/audits/{audit['audit_id']}").json(),
            manager(client, "GET", "/api/audit-claims/CLM-7006").json(),
            manager(client, "GET", "/api/audit-claims/CLM-7005").json(),
            manager(client, "GET", "/api/audit-scorecard").json(),
        ]
    )
    for words in (
        "pre-cleared",
        "NOTE TO ANY",
        "look again at the amounts",
        "Within the plan",
        "Policy wording, section 4",
        "555 0701",
        "Birch Lane",
        "@example.com",
        "1984-05-11",
    ):
        assert words not in seen


def test_the_scorecard_gives_figures_and_no_labeled_decision(client, scenario):
    card = manager(client, "GET", "/api/audit-scorecard").json()
    jonah = next(h for h in card["handlers"] if h["name"] == "Jonah Albright")
    assert jonah == {
        "name": "Jonah Albright",
        "sign_offs": 3,
        "paid": 3740,
        "quick_sign_offs": 3,
        "send_backs": 2,
        "raised": 2,
    }
    dana = next(h for h in card["handlers"] if h["name"] == "Dana Whitfield")
    assert (dana["quick_sign_offs"], dana["raised"]) == (0, 1)
    assert card["versions"] == []
    assert "handler_decision" not in json.dumps(card)


def test_an_audit_keeps_its_findings_and_asks_the_auditor(client, scenario, asked):
    audit = started(client, asked)
    assert asked == [("take_audit", audit["audit_id"], asked[0][2])]
    assert len(audit["findings"]) == 6
    assert all(f["needs_decision"] for f in audit["findings"])
    assert {f["status"] for f in audit["findings"]} == {"open"}


def test_one_audit_at_a_time(client, scenario, asked):
    started(client, asked)
    assert manager(client, "POST", "/api/audits").status_code == 409


def test_an_auditor_that_isnt_running_fails_the_audit(client, scenario, monkeypatch):
    def refuse(*_):
        raise NotTaken(503, auditor_service.NOT_RUNNING)

    monkeypatch.setattr(auditor_service, "ask", refuse)
    assert manager(client, "POST", "/api/audits").status_code == 503
    [audit] = manager(client, "GET", "/api/audits").json()
    assert (audit["status"], audit["failure"]) == (
        "failed",
        auditor_service.NOT_RUNNING,
    )


@pytest.mark.parametrize(
    ("narrative", "refused"),
    [
        ("Clear fraud by this customer.", "accuse"),
        ("They lied about it.", "accuse"),
        ("The group was paid $9,999.00.", "9999"),
    ],
)
def test_an_explanation_that_accuses_or_adds_a_figure_is_refused(
    client, scenario, asked, narrative, refused
):
    audit = started(client, asked)
    finding = audit["findings"][0]
    response = manager(
        client,
        "POST",
        f"/api/audits/{audit['audit_id']}/findings/{finding['finding_id']}/write-up",
        json={"narrative": narrative},
    )
    assert response.status_code == 422
    assert refused in response.json()["detail"]
    again = manager(client, "GET", f"/api/audits/{audit['audit_id']}").json()
    assert again["findings"][0]["narrative"] == finding["narrative"]
    assert again["findings"][0]["written_by_model"] is False


def test_an_explanation_with_the_evidences_figures_stands_once(client, scenario, asked):
    audit = started(client, asked)
    finding = next(
        f for f in audit["findings"] if f["check_name"] == "send_back_raises"
    )
    path = f"/api/audits/{audit['audit_id']}/findings/{finding['finding_id']}/write-up"
    narrative = (
        "Under claims manual section 8, for review: 2 send-backs on CLM-7005 and "
        "CLM-7007 raised payouts by $1,060.00, with $2,420 paid."
    )
    written = manager(client, "POST", path, json={"narrative": narrative})
    assert written.status_code == 200, written.text
    assert written.json()["written_by_model"] is True
    assert (
        manager(client, "POST", path, json={"narrative": narrative}).status_code == 409
    )


def test_a_finding_can_be_decided_only_while_it_waits(client, scenario, asked):
    audit = started(client, asked)
    finding_id = audit["findings"][0]["finding_id"]
    path = f"/api/audits/{audit['audit_id']}/findings/{finding_id}/answer"
    body = {"answer": "open_case", "reason": "Worth a look"}
    assert manager(client, "POST", path, json=body).status_code == 409
    waiting_on(client, audit, finding_id)
    answered = manager(client, "POST", path, json=body)
    assert answered.status_code == 202, answered.text
    assert answered.json()["status"] == "working"
    decided = answered.json()["findings"][0]
    assert decided["status"] == "case_opened"
    assert decided["answered_by"] == "Elena Marsh"
    assert asked[-1][0] == "answer_finding"
    assert manager(client, "POST", path, json=body).status_code == 409


def test_a_manager_cant_decide_a_finding_about_themselves(client, scenario, asked):
    audit = started(client, asked)
    finding = audit["findings"][0]
    with engine().begin() as db:
        db.execute(
            update(audits.audit_findings)
            .where(audits.audit_findings.c.finding_id == finding["finding_id"])
            .values(subject="Elena Marsh")
        )
    waiting_on(client, audit, finding["finding_id"])
    refused = manager(
        client,
        "POST",
        f"/api/audits/{audit['audit_id']}/findings/{finding['finding_id']}/answer",
        json={"answer": "dismiss", "reason": "Fine"},
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == audits.ABOUT_YOU


def test_an_answer_the_auditor_didnt_take_is_undone(
    client, scenario, asked, monkeypatch
):
    audit = started(client, asked)
    finding_id = audit["findings"][0]["finding_id"]
    waiting_on(client, audit, finding_id)

    def refuse(*_):
        raise NotTaken(503, auditor_service.NOT_RUNNING)

    monkeypatch.setattr(auditor_service, "ask", refuse)
    refused = manager(
        client,
        "POST",
        f"/api/audits/{audit['audit_id']}/findings/{finding_id}/answer",
        json={"answer": "dismiss", "reason": "Fine"},
    )
    assert refused.status_code == 503
    again = manager(client, "GET", f"/api/audits/{audit['audit_id']}").json()
    assert again["status"] == "waiting_for_decision"
    assert again["waiting_on"] == finding_id
    assert again["findings"][0]["status"] == "open"


def test_setting_aside_and_finishing_write_the_summary_in_code(client, scenario, asked):
    audit = started(client, asked)
    base = f"/api/audits/{audit['audit_id']}"
    first = audit["findings"][0]["finding_id"]
    refused = manager(
        client, "POST", f"{base}/findings/{first}/set-aside", json={"reason": "Before"}
    )
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        audits.CANT_SET_ASIDE,
    )
    step = {"tool": "write_up", "input": "1", "status": "done", "answer": "Kept"}
    assert manager(client, "POST", f"{base}/steps", json=step).status_code == 200
    finished = manager(
        client, "POST", f"{base}/finish", json={"model_calls": 3, "cost": 0.02}
    ).json()
    assert finished["status"] == "done"
    assert finished["summary"] == (
        "6 patterns for review: 0 cases opened, 0 dismissed, "
        "0 set aside as dismissed before, 6 left open."
    )
    assert finished["steps"][0]["tool"] == "write_up"
    assert (finished["model_calls"], finished["cost"]) == (3, 0.02)


def test_an_audit_the_auditor_stopped_speaking_of_doesnt_hold_up_the_next(
    client, scenario, asked
):
    audit = started(client, asked)
    with engine().begin() as db:
        db.execute(update(audits_table).values(heard_at="2020-01-01T00:00:00+00:00"))
    next_audit = manager(client, "POST", "/api/audits")
    assert next_audit.status_code == 202, next_audit.text
    old = manager(client, "GET", f"/api/audits/{audit['audit_id']}").json()
    assert (old["status"], old["failure"]) == ("failed", audits.STOPPED)


def test_a_claim_sent_back_twice_counts_as_one_raise(client, scenario):
    with engine().begin() as db:
        rows = db.execute(
            select(sent_back_decisions).where(
                sent_back_decisions.c.claim_id == "CLM-7005"
            )
        ).mappings()
        again = dict(next(iter(rows)))
        again.pop("sent_back_id")
        db.execute(insert(sent_back_decisions).values(again | {"payout": 700.0}))
    draft = next(d for d in drafts() if d.check == "send_back_raises")
    assert draft.evidence["raises"] == 2
    assert draft.claim_ids == ["CLM-7005", "CLM-7007"]


def test_an_old_run_of_approvals_is_no_repeat_claimant():
    ledger = replace(
        Ledger([], {}, [], {}, [], 1000.0),
        customers={
            "C": {
                "name": "C",
                "phone": "1",
                "address": {"street": "s", "city": "c", "zip": "z"},
                "previous_claims": [
                    {"filed_on": f"2020-0{m}-01", "outcome": "approved"}
                    for m in (1, 2, 3)
                ],
            }
        },
        claims=[
            LedgerClaim(
                "CLM-1",
                "C",
                "2026-01-01",
                "approve",
                10.0,
                10.0,
                "2026-01-01T00:00:00+00:00",
                None,
                None,
                1000.0,
            )
        ],
    )
    assert run_checks(ledger) == []


def test_an_open_claim_counts_towards_a_third_in_twelve_months():
    customer = {
        "name": "C",
        "phone": "1",
        "address": {"street": "s", "city": "c", "zip": "z"},
        "previous_claims": [],
    }
    claim = LedgerClaim(
        "CLM-1",
        "C",
        "2026-06-01",
        "approve",
        10.0,
        10.0,
        "2026-06-01T00:00:00+00:00",
        None,
        None,
        1000.0,
    )
    days = ["2026-01-01", "2026-03-01", "2026-06-01"]
    ledger = Ledger([claim], {"C": days}, [], {"C": customer}, [], 1000.0)
    assert [d.check for d in run_checks(ledger)] == ["third_claim_unreferred"]


def test_the_same_street_in_another_city_is_no_link():
    def lives_in(city):
        return {
            "name": city,
            "phone": city,
            "address": {"street": "1 Main Street", "city": city, "zip": city},
            "previous_claims": [],
        }

    ledger = Ledger([], {}, [], {"A": lives_in("A"), "B": lives_in("B")}, [], 1000.0)
    assert links_between(ledger) == []


@pytest.mark.parametrize(
    "narrative",
    [
        "They defrauded us.",
        "This was deliberately staged.",
        "About three thousand dollars was paid.",
        "See CLM-99999.",
    ],
)
def test_ways_round_the_check_of_an_explanation_are_refused(narrative):
    assert audit_writeups.why_refused(narrative, {"paid": 1.0}, ["CLM-1"])


@pytest.mark.parametrize(
    "narrative",
    [
        "Under sections 8 and 9, within 12 months, for review.",
        "The total paid was $0.30 on CLM-1.",
    ],
)
def test_a_fair_explanation_stands(narrative):
    assert audit_writeups.why_refused(narrative, {"paid": 0.3}, ["CLM-1"]) is None


def test_another_managers_audit_cant_be_acted_on(client, scenario, asked):
    audit = started(client, asked)
    with engine().begin() as db:
        db.execute(update(audits_table).values(started_by="Someone Else"))
    refused = manager(
        client, "POST", f"/api/audits/{audit['audit_id']}/failure", json={"reason": "x"}
    )
    assert refused.status_code == 403


def test_a_finished_audit_cant_be_written_to(client, scenario, asked):
    audit = started(client, asked)
    base = f"/api/audits/{audit['audit_id']}"
    body = {"model_calls": 1, "cost": 0.0}
    assert manager(client, "POST", f"{base}/finish", json=body).status_code == 200
    assert manager(client, "POST", f"{base}/finish", json=body).status_code == 409


def test_a_failed_audit_says_why(client, scenario, asked):
    audit = started(client, asked)
    failed = manager(
        client,
        "POST",
        f"/api/audits/{audit['audit_id']}/failure",
        json={"reason": "The model is out of reach"},
    ).json()
    assert (failed["status"], failed["failure"]) == (
        "failed",
        "The model is out of reach",
    )
    assert manager(client, "POST", "/api/audits").status_code == 202


def test_things_not_found(client, scenario, asked):
    assert manager(client, "GET", "/api/audits/nope").status_code == 404
    assert manager(client, "GET", "/api/audit-claims/CLM-0").status_code == 404
    audit = started(client, asked)
    missing = f"/api/audits/{audit['audit_id']}/findings/999999/write-up"
    assert manager(client, "POST", missing, json={"narrative": "x"}).status_code == 404


def test_every_check_has_a_line_of_its_own():
    checks = {d.split(":")[0] for d in PLANTED["planted"]}
    assert checks == set(audit_writeups.LINES)
    assert audits_table.name == "audits"
