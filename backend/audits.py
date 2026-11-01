"""The backend's operations on audits, for the claims operations manager alone: the
dashboard's, which start an audit, read it and decide a finding, each passing the
manager's sign-in on to the Auditor; and the Auditor's records of its work, which it
makes with the same sign-in. Nothing here gives the Auditor a customer's words, their
contact details or a handler's decision on a labeled claim."""

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Connection, RowMapping, insert, select, update

from backend import audit_checks, audit_writeups, auditor_service, scoreboard, scoring
from backend.asking import commit_and_ask
from backend.audit_checks import Ledger, LedgerClaim, LedgerSendBack
from backend.database import (
    audit_findings,
    audit_steps,
    audits,
    claim_view,
    claims,
    customers,
    locks,
    now,
    policies,
    runs,
    sent_back_decisions,
)
from backend.dependencies import Database, SignedIn, SignIn
from backend.lookups import current_settings
from backend.models import (
    Audit,
    AuditClaim,
    AuditFinding,
    AuditFinishRequest,
    AuditPauseRequest,
    AuditSentBack,
    AuditSetAsideRequest,
    AuditStatus,
    AuditStep,
    AuditStepRequest,
    AuditWriteUp,
    DecisionKind,
    FindingAnswer,
    FindingAnswerRequest,
    FindingStatus,
    Handler,
    HandlerLens,
    RunStatus,
    Scorecard,
    TurnFailureRequest,
    VersionLens,
)

router = APIRouter()

AUDITS = "/api/audits"
AUDIT = AUDITS + "/{audit_id}"
FINDING = AUDIT + "/findings/{finding_id}"
ONLY_THE_MANAGER = "Only the claims operations manager can audit. {name} can't."
AUDIT_NOT_FOUND = "Audit {audit_id} not found"
FINDING_NOT_FOUND = "Finding {finding_id} not found"
CLAIM_NOT_FOUND = "Claim {claim_id} not found"
ONE_AT_A_TIME = "Audit #{audit_id} is still going"
NOT_WAITING = "This finding isn't waiting for a decision"
ABOUT_YOU = "This finding is about you, so someone else must decide it"
ALREADY_WRITTEN = "This finding has its explanation"
ANOTHERS = "This audit is {name}'s"
NOT_WORKING = "This audit isn't working"
CANT_SET_ASIDE = "You haven't dismissed this pattern on these claims before"
NOT_OPEN = "This finding has been decided"
STOPPED = "The Auditor stopped answering. Start another audit."
# An audit the Auditor hasn't spoken of for this long has stopped.
STOPPED_AFTER = timedelta(minutes=10)
# Audits start one at a time.
AUDITS_LOCK = "audits"


def manager(handler: SignedIn) -> Handler:
    """Return the signed-in handler, or raise a 403 unless they can audit."""
    if not handler.can_audit:
        raise HTTPException(403, ONLY_THE_MANAGER.format(name=handler.name))
    return handler


Manager = Annotated[Handler, Depends(manager)]


def ledger_of(db: Connection) -> Ledger:
    """Read what the checks work on: the queue's claims, not an evaluation's copies,
    those decided in full and the rest for the days they were filed, the decisions
    sent back, and the customers and policies."""
    rows = db.execute(claim_view.where(claims.c.evaluation_id.is_(None)))
    ledger_claims, filed = [], defaultdict(list)
    for row in rows.mappings():
        record = row["record"]
        filed[record["customer_id"]].append(record["submitted_on"])
        if row["decision"] is None:
            continue
        ledger_claims.append(
            LedgerClaim(
                claim_id=row["claim_id"],
                customer_id=record["customer_id"],
                submitted_on=record["submitted_on"],
                decision=row["decision"],
                payout=row["payout"],
                paid=row["amount"],
                decided_at=row["decided_at"],
                signed_off_by=row["signed_off_by"],
                signed_off_at=row["signed_off_at"],
                approval_limit=row["approval_limit"],
            )
        )
    sent = db.execute(select(sent_back_decisions)).mappings()
    return Ledger(
        claims=ledger_claims,
        filed=dict(filed),
        sent_back=[
            LedgerSendBack(s["claim_id"], s["decision"], s["payout"], s["sent_back_by"])
            for s in sent
        ],
        customers={
            row["customer_id"]: row["record"]
            for row in db.execute(select(customers)).mappings()
        },
        policies=list(db.execute(select(policies.c.record)).scalars()),
        limit=current_settings(db).approval_limit,
    )


def audit_row(db: Connection, audit_id: str) -> RowMapping:
    query = select(audits).where(audits.c.audit_id == audit_id)
    row = db.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, AUDIT_NOT_FOUND.format(audit_id=audit_id))
    return row


def own_audit(db: Connection, audit_id: str, handler: Handler) -> RowMapping:
    """An audit this manager started, or a 403: only they may act on it."""
    row = audit_row(db, audit_id)
    if row["started_by"] != handler.name:
        raise HTTPException(403, ANOTHERS.format(name=row["started_by"]))
    return row


def working_audit(db: Connection, audit_id: str, handler: Handler) -> RowMapping:
    """An audit of this manager's that the Auditor is working, or a refusal."""
    row = own_audit(db, audit_id, handler)
    if row["status"] != AuditStatus.WORKING:
        raise HTTPException(409, NOT_WORKING)
    return row


def heard(db: Connection, audit_id: str) -> None:
    set_status(db, audit_id, heard_at=now())


def finding_row(db: Connection, audit_id: str, finding_id: int) -> RowMapping:
    query = select(audit_findings).where(
        audit_findings.c.audit_id == audit_id,
        audit_findings.c.finding_id == finding_id,
    )
    row = db.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, FINDING_NOT_FOUND.format(finding_id=finding_id))
    return row


def asked_finding(
    audit_id: str, finding_id: int, handler: Manager, db: Database
) -> RowMapping:
    """The finding a route names, once the signed-in handler is the manager."""
    return finding_row(db, audit_id, finding_id)


AskedFinding = Annotated[RowMapping, Depends(asked_finding)]


def findings_of(db: Connection, audit_id: str) -> list[AuditFinding]:
    query = (
        select(audit_findings)
        .where(audit_findings.c.audit_id == audit_id)
        .order_by(audit_findings.c.finding_id)
    )
    return [AuditFinding(**row) for row in db.execute(query).mappings()]


def to_audit(db: Connection, row: RowMapping) -> Audit:
    query = (
        select(audit_steps)
        .where(audit_steps.c.audit_id == row["audit_id"])
        .order_by(audit_steps.c.step_id)
    )
    steps = [AuditStep(**step) for step in db.execute(query).mappings()]
    return Audit(**row, findings=findings_of(db, row["audit_id"]), steps=steps)


def set_status(db: Connection, audit_id: str, **values: object) -> None:
    db.execute(update(audits).where(audits.c.audit_id == audit_id).values(**values))


def keep_findings(db: Connection, audit_id: str) -> None:
    """Run the checks, and keep what they find with the audit."""
    ledger = ledger_of(db)
    for draft in audit_checks.run_checks(ledger):
        db.execute(
            insert(audit_findings).values(
                audit_id=audit_id,
                check_name=draft.check,
                subject=draft.subject,
                subject_name=draft.subject_name,
                fingerprint=draft.fingerprint,
                score=draft.score,
                needs_decision=draft.needs_decision(ledger.limit),
                claim_ids=draft.claim_ids,
                exposure=draft.exposure,
                evidence=draft.evidence,
                narrative=audit_writeups.LINES[draft.check],
                written_by_model=False,
                status=FindingStatus.OPEN,
            )
        )


def stop_the_silent(db: Connection) -> None:
    """Fail any audit still working that the Auditor hasn't spoken of lately, as after
    a restart, so it can't hold up the next."""
    working = select(audits).where(audits.c.status == AuditStatus.WORKING)
    moment = datetime.now(UTC) - STOPPED_AFTER
    for row in db.execute(working).mappings().all():
        if datetime.fromisoformat(row["heard_at"]) < moment:
            fail_untaken(db, row["audit_id"], STOPPED)


def refuse_while_going(db: Connection) -> None:
    """Refuse a new audit while another goes, holding the lock until this request
    commits, so two can't start at once."""
    db.execute(select(locks).where(locks.c.name == AUDITS_LOCK).with_for_update())
    stop_the_silent(db)
    query = select(audits.c.audit_id).where(
        audits.c.status.in_([AuditStatus.WORKING, AuditStatus.WAITING_FOR_DECISION])
    )
    going = db.execute(query).scalars().first()
    if going is not None:
        raise HTTPException(409, ONE_AT_A_TIME.format(audit_id=going))


def fail_untaken(db: Connection, audit_id: str, reason: str) -> None:
    set_status(
        db, audit_id, status=AuditStatus.FAILED, failure=reason, finished_at=now()
    )


@router.post(AUDITS, operation_id="start_audit", status_code=202)
def start_audit(handler: Manager, sign_in: SignIn, db: Database) -> Audit:
    """Start an audit: the checks run in code, then the Auditor explains them."""
    refuse_while_going(db)
    audit_id = f"audit-{uuid4()}"
    db.execute(
        insert(audits).values(
            audit_id=audit_id,
            started_by=handler.name,
            status=AuditStatus.WORKING,
            started_at=now(),
            heard_at=now(),
            model_calls=0,
            cost=0.0,
        )
    )
    keep_findings(db, audit_id)
    commit_and_ask(
        db,
        partial(auditor_service.ask, "take_audit", audit_id, sign_in),
        partial(fail_untaken, db, audit_id),
    )
    return to_audit(db, audit_row(db, audit_id))


@router.get(AUDITS, operation_id="list_audits")
def list_audits(handler: Manager, db: Database) -> list[Audit]:
    """List the audits, newest first."""
    stop_the_silent(db)
    rows = db.execute(select(audits).order_by(audits.c.started_at.desc())).mappings()
    return [to_audit(db, row) for row in rows.all()]


def lenient(claim: scoring.Answer, handler: scoring.Answer) -> bool:
    """Say whether the agent gave more than the handler: an approval they didn't
    make, or a higher payout on one they did."""
    if claim.decision != DecisionKind.APPROVE:
        return False
    if handler.decision != DecisionKind.APPROVE:
        return True
    return claim.payout > handler.payout + scoring.PAYOUT_TOLERANCE


def strict(claim: scoring.Answer, handler: scoring.Answer) -> bool:
    """Say whether the agent gave less than the handler."""
    return (
        handler.decision == DecisionKind.APPROVE
        and not scoring.is_right(claim, handler)
        and not lenient(claim, handler)
    )


def version_lenses(db: Connection) -> list[VersionLens]:
    """Each version's accuracy and leniency across its finished evaluations, as
    figures only: no decision on any labeled claim."""
    query = select(runs).where(
        runs.c.evaluation_set.is_not(None), runs.c.status == RunStatus.FINISHED
    )
    rows = db.execute(query).mappings().all()
    expected = scoreboard.expected_answers(db)
    scored = scoreboard.score_all(db, list(rows), expected)
    lenses = []
    for version in sorted({e.version for e in scored}):
        copies = [c for e in scored if e.version == version for c in e.claims]
        pairs = [
            (
                scoring.answer_of(c.decision, c.payout),
                scoring.Answer(c.handler_decision, c.handler_payout),
            )
            for c in copies
        ]
        count = len(pairs) or 1
        lenses.append(
            VersionLens(
                version=version,
                evaluations=sum(e.version == version for e in scored),
                claims=len(pairs),
                accuracy=sum(c.right for c in copies) / count,
                lenient_share=sum(lenient(*p) for p in pairs) / count,
                strict_share=sum(strict(*p) for p in pairs) / count,
                overpaid=sum(
                    max(a.payout - h.payout, 0) for a, h in pairs if lenient(a, h)
                ),
            )
        )
    return lenses


def handler_lenses(db: Connection) -> list[HandlerLens]:
    """Each handler's sign-offs and send-backs on the queue."""
    ledger = ledger_of(db)
    now_paid = {c.claim_id: c for c in ledger.claims}
    names = {c.signed_off_by for c in ledger.claims if c.signed_off_by}
    names |= {s.sent_back_by for s in ledger.sent_back}
    lenses = []
    for name in sorted(names):
        signed = [c for c in ledger.claims if c.signed_off_by == name]
        sent = [s for s in ledger.sent_back if s.sent_back_by == name]
        lenses.append(
            HandlerLens(
                name=name,
                sign_offs=len(signed),
                paid=sum(c.paid or 0 for c in signed),
                quick_sign_offs=sum(
                    audit_checks.seconds_to_sign_off(c) < audit_checks.QUICK_SECONDS
                    for c in signed
                ),
                send_backs=len(sent),
                raised=sum(
                    s.claim_id in now_paid and now_paid[s.claim_id].payout > s.payout
                    for s in sent
                ),
            )
        )
    return lenses


@router.get("/api/audit-scorecard", operation_id="get_audit_scorecard")
def get_audit_scorecard(handler: Manager, db: Database) -> Scorecard:
    """Get each version's accuracy and leniency and each handler's sign-offs."""
    return Scorecard(versions=version_lenses(db), handlers=handler_lenses(db))


@router.get("/api/audit-claims/{claim_id}", operation_id="get_audit_claim")
def get_audit_claim(claim_id: str, handler: Manager, db: Database) -> AuditClaim:
    """Get a queue claim's facts: no story, document, reason or note."""
    query = claim_view.where(
        claims.c.claim_id == claim_id, claims.c.evaluation_id.is_(None)
    )
    row = db.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, CLAIM_NOT_FOUND.format(claim_id=claim_id))
    earlier = select(sent_back_decisions).where(
        sent_back_decisions.c.claim_id == claim_id
    )
    record = row["record"]
    return AuditClaim(
        claim_id=claim_id,
        customer_id=record["customer_id"],
        customer_name=row["customer_name"],
        claim_type=record["claim_type"],
        submitted_on=record["submitted_on"],
        amount_claimed=sum(item["amount"] for item in record["items"]),
        status=row["status"],
        decision=row["decision"],
        payout=row["payout"],
        decided_at=row["decided_at"],
        paid=row["amount"],
        signed_off_by=row["signed_off_by"],
        signed_off_at=row["signed_off_at"],
        sent_back=[
            AuditSentBack(
                decision=s["decision"],
                payout=s["payout"],
                sent_back_by=s["sent_back_by"],
                sent_back_at=s["sent_back_at"],
            )
            for s in db.execute(earlier).mappings()
        ],
    )


@router.get(AUDIT, operation_id="get_audit")
def get_audit(audit_id: str, handler: Manager, db: Database) -> Audit:
    """Get an audit, with its findings and the Auditor's steps."""
    return to_audit(db, audit_row(db, audit_id))


@router.post(FINDING + "/write-up", operation_id="write_up_finding")
def write_up_finding(
    audit_id: str,
    finding_id: int,
    request: AuditWriteUp,
    handler: Manager,
    db: Database,
) -> AuditFinding:
    """Keep the Auditor's explanation, unless it accuses someone or adds a figure."""
    working_audit(db, audit_id, handler)
    heard(db, audit_id)
    row = finding_row(db, audit_id, finding_id)
    if row["written_by_model"]:
        raise HTTPException(409, ALREADY_WRITTEN)
    reason = audit_writeups.why_refused(
        request.narrative, row["evidence"], row["claim_ids"]
    )
    if reason:
        raise HTTPException(422, reason)
    update_finding(db, finding_id, narrative=request.narrative, written_by_model=True)
    return AuditFinding(**finding_row(db, audit_id, finding_id))


def update_finding(db: Connection, finding_id: int, **values: object) -> None:
    db.execute(
        update(audit_findings)
        .where(audit_findings.c.finding_id == finding_id)
        .values(**values)
    )


@router.post(FINDING + "/set-aside", operation_id="set_aside_finding")
def set_aside_finding(
    finding: AskedFinding,
    request: AuditSetAsideRequest,
    handler: Manager,
    db: Database,
) -> AuditFinding:
    """Set aside a finding this manager has dismissed before on the same claims."""
    audit_id, finding_id = finding["audit_id"], finding["finding_id"]
    working_audit(db, audit_id, handler)
    refuse_unless_dismissed_before(db, finding, handler)
    update_finding(
        db,
        finding_id,
        status=FindingStatus.SET_ASIDE,
        answer_reason=request.reason,
        needs_decision=False,
    )
    return AuditFinding(**finding_row(db, audit_id, finding_id))


def refuse_unless_dismissed_before(
    db: Connection, finding: RowMapping, handler: Handler
) -> None:
    """Refuse unless the finding is open, not about this manager, and they dismissed
    the same pattern on all these claims, so no new claim is set aside unseen."""
    if finding["status"] != FindingStatus.OPEN:
        raise HTTPException(409, NOT_OPEN)
    if finding["subject"] == handler.name:
        raise HTTPException(403, ABOUT_YOU)
    earlier = select(audit_findings.c.claim_ids).where(
        audit_findings.c.fingerprint == finding["fingerprint"],
        audit_findings.c.status == FindingStatus.DISMISSED,
        audit_findings.c.answered_by == handler.name,
    )
    seen = list(db.execute(earlier).scalars())
    if not any(set(finding["claim_ids"]) <= set(claim_ids) for claim_ids in seen):
        raise HTTPException(409, CANT_SET_ASIDE)


@router.post(FINDING + "/answer", operation_id="answer_finding", status_code=202)
def answer_finding(
    finding: AskedFinding,
    request: FindingAnswerRequest,
    handler: Manager,
    sign_in: SignIn,
    db: Database,
) -> Audit:
    """Open a case on the finding the audit waits on, or dismiss it, with a reason."""
    audit_id, finding_id = finding["audit_id"], finding["finding_id"]
    own_audit(db, audit_id, handler)
    if finding["subject"] == handler.name:
        raise HTTPException(403, ABOUT_YOU)
    # Only one answer takes the wait, so a double press can't ask twice.
    taken = db.execute(
        update(audits)
        .where(audits.c.audit_id == audit_id, audits.c.waiting_on == finding_id)
        .values(status=AuditStatus.WORKING, waiting_on=None, heard_at=now())
    )
    if taken.rowcount == 0:
        raise HTTPException(409, NOT_WAITING)
    status = (
        FindingStatus.CASE_OPENED
        if request.answer == FindingAnswer.OPEN_CASE
        else FindingStatus.DISMISSED
    )
    update_finding(
        db,
        finding_id,
        status=status,
        answer_reason=request.reason,
        answered_by=handler.name,
        answered_at=now(),
    )
    undo: Callable[[str], object] = partial(undo_answer, db, audit_id, finding_id)
    commit_and_ask(
        db, partial(auditor_service.ask, "answer_finding", audit_id, sign_in), undo
    )
    return to_audit(db, audit_row(db, audit_id))


def undo_answer(db: Connection, audit_id: str, finding_id: int, reason: str) -> None:
    """Put a finding back to waiting when the Auditor didn't take the answer."""
    update_finding(
        db,
        finding_id,
        status=FindingStatus.OPEN,
        answer_reason=None,
        answered_by=None,
        answered_at=None,
    )
    set_status(
        db, audit_id, status=AuditStatus.WAITING_FOR_DECISION, waiting_on=finding_id
    )


@router.post(AUDIT + "/steps", operation_id="record_audit_step")
def record_audit_step(
    audit_id: str, request: AuditStepRequest, handler: Manager, db: Database
) -> Audit:
    """Record a step the Auditor took."""
    working_audit(db, audit_id, handler)
    heard(db, audit_id)
    db.execute(
        insert(audit_steps).values(audit_id=audit_id, at=now(), **request.model_dump())
    )
    return to_audit(db, audit_row(db, audit_id))


@router.post(AUDIT + "/pause", operation_id="pause_audit")
def pause_audit(
    audit_id: str, request: AuditPauseRequest, handler: Manager, db: Database
) -> Audit:
    """Record that the audit waits for the manager's decision on a finding."""
    working_audit(db, audit_id, handler)
    if finding_row(db, audit_id, request.finding_id)["status"] != FindingStatus.OPEN:
        raise HTTPException(409, NOT_OPEN)
    set_status(
        db,
        audit_id,
        status=AuditStatus.WAITING_FOR_DECISION,
        waiting_on=request.finding_id,
        model_calls=request.model_calls,
        cost=request.cost,
    )
    return to_audit(db, audit_row(db, audit_id))


@router.post(AUDIT + "/finish", operation_id="finish_audit")
def finish_audit(
    audit_id: str, request: AuditFinishRequest, handler: Manager, db: Database
) -> Audit:
    """End an audit, with its summary written from the records."""
    working_audit(db, audit_id, handler)
    found = findings_of(db, audit_id)
    opened = sum(f.status == FindingStatus.CASE_OPENED for f in found)
    dismissed = sum(f.status == FindingStatus.DISMISSED for f in found)
    set_aside = sum(f.status == FindingStatus.SET_ASIDE for f in found)
    left = sum(f.status == FindingStatus.OPEN for f in found)
    summary = (
        f"{len(found)} patterns for review: {opened} cases opened, "
        f"{dismissed} dismissed, {set_aside} set aside as dismissed before, "
        f"{left} left open."
    )
    set_status(
        db,
        audit_id,
        status=AuditStatus.DONE,
        summary=summary,
        model_calls=request.model_calls,
        cost=request.cost,
        finished_at=now(),
    )
    return to_audit(db, audit_row(db, audit_id))


@router.post(AUDIT + "/failure", operation_id="fail_audit")
def fail_audit(
    audit_id: str, request: TurnFailureRequest, handler: Manager, db: Database
) -> Audit:
    """End an audit that failed, with why."""
    working_audit(db, audit_id, handler)
    fail_untaken(db, audit_id, request.reason)
    return to_audit(db, audit_row(db, audit_id))
