"""Working an audit, and the manager's answer on a finding: the audit checked with the
app first, then its model and graph built, the graph run on the audit's thread, and
the app told how it ended: paused on a finding, finished or failed."""

import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from langgraph.types import Command, StateSnapshot

from agent import tool_route
from agent.auditor import app_api
from agent.auditor.graph import AuditorGraph, auditor_graph
from agent.auditor.tools import AuditorContext
from agent.console import describe
from agent.openrouter import chat_model

log = logging.getLogger(__name__)

NOT_WORKING = "Audit {audit_id} isn't working"
NOTHING_TO_RESUME = "Audit {audit_id} isn't waiting for an answer"


class NotThisAudit(Exception):
    """The Auditor won't work the audit the app asked for, and why."""


@dataclass
class AuditWork:
    """An audit the app asked the Auditor to work, with the manager's sign-in."""

    sign_in: str = field(repr=False)
    manager: dict[str, Any]
    audit_id: str


def the_audit(sign_in: str, audit_id: str) -> AuditWork:
    """Ask the app who is signed in and read the audit, before any model call. The
    app refuses a sign-in it doesn't accept and anyone but the manager."""
    manager = app_api.get_signed_in_handler(sign_in)
    audit = app_api.get_audit(sign_in, audit_id)
    if audit["status"] != app_api.WORKING:
        raise NotThisAudit(NOT_WORKING.format(audit_id=audit_id))
    return AuditWork(sign_in, manager, audit_id)


def auditor_model(sign_in: str) -> ChatOpenAI:
    """The model the app names, the Copilot's, at its reasoning effort."""
    named = app_api.get_model(sign_in)
    return chat_model(named["model"], named["reasoning_effort"])


def thread_of(audit_id: str) -> RunnableConfig:
    """The audit's thread, where its graph saves its state, one tool at a time."""
    return {"configurable": {"thread_id": audit_id}, "max_concurrency": 1}


def tell_the_app(audit: AuditWork, saved: StateSnapshot) -> None:
    """Tell the app how the graph stopped: paused on a finding, or finished."""
    calls, cost = saved.values["model_calls"], saved.values["cost"]
    if saved.interrupts:
        finding_id = saved.interrupts[0].value["finding_id"]
        app_api.pause(audit.sign_in, audit.audit_id, finding_id, calls, cost)
    else:
        app_api.finish(audit.sign_in, audit.audit_id, calls, cost)


def run(
    audit: AuditWork,
    start: dict[str, Any] | Command,
    saver: BaseCheckpointSaver[Any],
    store: BaseStore,
) -> None:
    """Run the graph from a start, saving every step, then tell the app how it
    ended. An audit that raises is failed with the error in one line."""
    try:
        graph: AuditorGraph = auditor_graph(auditor_model(audit.sign_in), saver, store)
        config = thread_of(audit.audit_id)
        context = AuditorContext(
            audit.sign_in,
            audit.manager,
            audit.audit_id,
            tool_route.from_environment(),
        )
        graph.invoke(start, config, context=context, durability="sync")
        tell_the_app(audit, graph.get_state(config))
    except Exception as error:  # the audit fails, and nothing else
        log.warning("Audit %s failed: %s", audit.audit_id, describe(error))
        app_api.fail(audit.sign_in, audit.audit_id, describe(error))


def take_audit(
    audit: AuditWork, saver: BaseCheckpointSaver[Any], store: BaseStore
) -> None:
    """Work a new audit."""
    run(audit, {"model_calls": 0, "cost": 0.0, "waiting_on": 0}, saver, store)


def check_paused(
    audit: AuditWork, saver: BaseCheckpointSaver[Any], store: BaseStore
) -> None:
    """Refuse an audit whose graph isn't paused for the manager's decision."""
    graph = auditor_graph(auditor_model(audit.sign_in), saver, store)
    if not graph.get_state(thread_of(audit.audit_id)).interrupts:
        raise NotThisAudit(NOTHING_TO_RESUME.format(audit_id=audit.audit_id))


def answer_finding(
    audit: AuditWork, saver: BaseCheckpointSaver[Any], store: BaseStore
) -> None:
    """Carry a paused audit on. The app already holds the manager's answer, which
    the graph reads from it."""
    run(audit, Command(resume=True), saver, store)
