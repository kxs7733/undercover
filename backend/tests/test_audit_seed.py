"""The Auditor's planted scenario: it reads through the app as any decided claim
does, and leaves the queue's own claims and the evaluation sets alone."""

from sqlalchemy import func, select

from backend import audit_seed
from backend.database import engine, handler_decisions, held_out_claims
from backend.tests.dashboard_reads import read


def counts():
    with engine().connect() as db:
        return (
            db.execute(select(func.count()).select_from(handler_decisions)).scalar(),
            db.execute(select(func.count()).select_from(held_out_claims)).scalar(),
        )


def test_the_scenario_reads_through_the_app_and_runs_twice(dashboard, capsys):
    before = counts()
    queue_before = read(dashboard, "/api/claims").json()
    audit_seed.main()
    audit_seed.main()
    assert "18 decided claims and 11 customers" in capsys.readouterr().out
    queue = read(dashboard, "/api/claims").json()
    added = [c for c in queue if c["claim_id"].startswith("CLM-7")]
    assert len(added) == 18
    assert len(queue) == len(queue_before) + 18
    assert {c["status"] for c in added} == {"decided"}
    assert counts() == before
    claim = read(dashboard, "/api/claims/CLM-7005").json()
    assert claim["payment"]["amount"] == 1180
    assert claim["decision"]["signed_off_by"] == "Jonah Albright"
    assert claim["sent_back_decisions"][0]["payout"] == 720
