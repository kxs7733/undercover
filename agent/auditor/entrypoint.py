"""The Auditor as an AgentCore app: one entrypoint takes each payload the app sends, an
audit or the manager's answer on a finding, checks with the app who is signed in
before it answers, and hands the work to work.py on a thread of its own, which its
/ping reports as busy until it ends. npm run dev serves it on 127.0.0.1:8082. Nothing
happens as it's imported: it gets ready on its first request. It asks for no key:
everything it does carries the manager's sign-in, which the app checks on every
call."""

import logging
from collections.abc import Callable
from typing import Annotated, Any, Literal

from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from pydantic import Field, TypeAdapter

from agent.agentcore_app import (
    ACCEPTED,
    HEALTHY,
    Health,
    Operation,
    Ready,
    in_background,
    read,
)
from agent.auditor import app_api, work
from agent.checkpoints import Pool, open_checkpoint_pool
from agent.console import show_reports

log = logging.getLogger(__name__)

NOT_READY = "The Auditor couldn't get ready: {error}"
# Supabase's free plan allows 15 connections, and the app, the agent and the Copilot
# may each take 4.
CONNECTIONS = 2

app = BedrockAgentCoreApp()

SignIn = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]+$", repr=False)]


class TakeAudit(Operation):
    operation: Literal["take_audit"]
    audit_id: str
    sign_in: SignIn


class AnswerFinding(Operation):
    operation: Literal["answer_finding"]
    audit_id: str
    sign_in: SignIn


Payload = Annotated[
    Health | TakeAudit | AnswerFinding, Field(discriminator="operation")
]
PAYLOADS: TypeAdapter[Payload] = TypeAdapter(Payload)


def get_ready() -> Pool:
    """Set up the report lines, open the pool and set up the store's tables."""
    show_reports()
    pool = open_checkpoint_pool(CONNECTIONS)
    PostgresStore(pool).setup()
    return pool


ready: Ready[Pool] = Ready(get_ready, NOT_READY)


def hand_on(audit: work.AuditWork, job: Callable[[], None]) -> None:
    """Work an audit in the background. An audit that raises, which only happens
    when the app can't be told it failed, is logged."""

    def logged() -> None:
        try:
            job()
        except (
            Exception
        ):  # an audit the app couldn't be told about stops, and nothing else
            log.exception("Audit %s stopped", audit.audit_id)

    in_background(app, "audit", logged)


def start(request: Payload, pool: Pool) -> dict[str, Any]:
    """Hand an operation its work, and answer that the Auditor took it."""
    if isinstance(request, Health):
        return HEALTHY
    audit = work.the_audit(request.sign_in, request.audit_id)
    saver, store = PostgresSaver(pool), PostgresStore(pool)
    if isinstance(request, TakeAudit):
        hand_on(audit, lambda: work.take_audit(audit, saver, store))
    else:
        work.check_paused(audit, saver, store)
        hand_on(audit, lambda: work.answer_finding(audit, saver, store))
    return ACCEPTED


@app.entrypoint
def invoke(payload: Any, context: RequestContext) -> dict[str, Any]:
    """Take one payload: get ready, read it, and start its work, or say why the
    Auditor won't."""
    pool = ready.get()
    request = read(PAYLOADS, payload)
    try:
        return start(request, pool)
    except work.NotThisAudit as refusal:
        return {"refused": str(refusal)}
    except app_api.Refused as refused:  # the app's, such as a sign-in it refuses
        return {"refused": str(refused.detail)}
