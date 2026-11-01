"""Add the Auditor's planted scenario to a seeded database, from data/audit/, with:
uv run -m backend.audit_seed. It replaces any earlier copy of itself and leaves the
queue's own claims and the evaluation sets alone. Its claims are already decided,
so no dispatch picks them up and no model is called."""

from typing import Any

from sqlalchemy import Connection, Engine, delete, insert

from backend.database import (
    claims,
    customers,
    decisions,
    engine,
    handlers,
    load,
    payments,
    policies,
    sent_back_decisions,
)
from backend.documents import manual_version
from backend.models import Status

SCENARIO = "audit/scenario.json"
SECTION = "Policy wording, section 4"
SCENARIO_REASON = "Within the plan's limits, with receipts."
LIMIT = 1000.0


def clear(db: Connection, scenario: dict[str, Any]) -> None:
    """Remove any earlier copy of the scenario."""
    claim_ids = [c["record"]["claim_id"] for c in scenario["claims"]]
    for table in (sent_back_decisions, payments, decisions):
        db.execute(delete(table).where(table.c.claim_id.in_(claim_ids)))
    db.execute(delete(claims).where(claims.c.claim_id.in_(claim_ids)))
    policy_ids = [p["policy_id"] for p in scenario["policies"]]
    db.execute(delete(policies).where(policies.c.policy_id.in_(policy_ids)))
    customer_ids = [c["customer_id"] for c in scenario["customers"]]
    db.execute(delete(customers).where(customers.c.customer_id.in_(customer_ids)))
    handler_ids = [h["handler_id"] for h in scenario["handlers"]]
    db.execute(delete(handlers).where(handlers.c.handler_id.in_(handler_ids)))


def add_claim(db: Connection, claim: dict[str, Any], version: str) -> None:
    """Add a claim as the agent decided it, with what it was sent back from and its
    payment."""
    record, claim_id = claim["record"], claim["record"]["claim_id"]
    db.execute(
        insert(claims).values(
            claim_id=claim_id,
            customer_id=record["customer_id"],
            record=record,
            status=Status.DECIDED,
            attempts=1,
        )
    )
    db.execute(
        insert(decisions).values(
            claim_id=claim_id,
            decision=claim["decision"],
            payout=claim["payout"],
            section=SECTION,
            reason=SCENARIO_REASON,
            decided_at=claim["decided_at"],
            decided_by=claim["decided_by"],
            manual_version=version,
            approval_limit=LIMIT,
            signed_off_by=claim["signed_off_by"],
            signed_off_at=claim["signed_off_at"],
        )
    )
    for earlier in claim["sent_back"]:
        db.execute(
            insert(sent_back_decisions).values(
                claim_id=claim_id,
                decision=earlier["decision"],
                payout=earlier["payout"],
                section=earlier["section"],
                reason=SCENARIO_REASON,
                decided_by=claim["decided_by"],
                decided_at=earlier["decided_at"],
                manual_version=version,
                note=earlier["note"],
                sent_back_by=earlier["sent_back_by"],
                sent_back_at=earlier["sent_back_at"],
            )
        )
    if claim["paid"]:
        paid_at = claim["signed_off_at"] or claim["decided_at"]
        db.execute(
            insert(payments).values(
                claim_id=claim_id, amount=claim["payout"], paid_at=paid_at
            )
        )


def add_scenario(database: Engine) -> dict[str, int]:
    """Add the scenario to a seeded database, and count what it added."""
    scenario = load(SCENARIO)
    with database.begin() as db:
        clear(db, scenario)
        db.execute(insert(handlers), scenario["handlers"])
        db.execute(
            insert(customers),
            [
                {"customer_id": c["customer_id"], "name": c["name"], "record": c}
                for c in scenario["customers"]
            ],
        )
        db.execute(
            insert(policies),
            [{"policy_id": p["policy_id"], "record": p} for p in scenario["policies"]],
        )
        version = manual_version(db)
        for claim in scenario["claims"]:
            add_claim(db, claim, version)
    return {
        "claims": len(scenario["claims"]),
        "customers": len(scenario["customers"]),
    }


def main() -> None:
    """Add the scenario and say what it added."""
    counts = add_scenario(engine())
    print(
        f"Added the Auditor's scenario: {counts['claims']} decided claims and "
        f"{counts['customers']} customers"
    )


if __name__ == "__main__":
    main()
