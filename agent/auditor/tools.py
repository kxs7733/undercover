"""The Auditor's tools, which reach the app through its API with the manager's sign-in
and the context layer on the route in their context, and the context they read. Each
only reads, apart from writing up a finding's explanation, which the app checks."""

from dataclasses import dataclass, field
from typing import Annotated, Any

from langchain.tools import ToolRuntime, tool
from pydantic import StringConstraints

from agent.auditor import app_api
from agent.context_tools import CONTEXT_TOOLS
from agent.json_text import as_json
from agent.routes import Route

Narrative = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


@dataclass
class AuditorContext:
    """Who the Auditor works for on an audit: the manager's sign-in, the manager as
    the app gave them, the audit and the route its context layer tools take.
    LangGraph hands it to the nodes and the tools and never saves it."""

    sign_in: str = field(repr=False)
    manager: dict[str, Any]
    audit_id: str
    route: Route


@tool
def list_findings(runtime: ToolRuntime[AuditorContext]) -> str:
    """List this audit's findings: each one's check, subject, score, claims, the
    dollars paid and its evidence, all worked out in code."""
    context = runtime.context
    audit = app_api.get_audit(context.sign_in, context.audit_id)
    return as_json(audit["findings"])


@tool
def get_scorecard(runtime: ToolRuntime[AuditorContext]) -> str:
    """Get each agent version's accuracy and leniency, and each handler's sign-offs
    and send-backs, as figures."""
    return as_json(app_api.get_scorecard(runtime.context.sign_in))


@tool
def get_claim_facts(claim_id: str, runtime: ToolRuntime[AuditorContext]) -> str:
    """Get a queue claim's facts: its dates, amounts, decision, payment, sign-off and
    any send-backs."""
    return as_json(app_api.get_claim(runtime.context.sign_in, claim_id))


@tool
def write_up_finding(
    finding_id: int, narrative: Narrative, runtime: ToolRuntime[AuditorContext]
) -> str:
    """Explain one finding to the manager in two or three plain sentences. It is
    refused if it accuses anyone or gives a figure that isn't in the evidence."""
    context = runtime.context
    written = app_api.write_up(context.sign_in, context.audit_id, finding_id, narrative)
    return f"Kept for finding {written['finding_id']}."


AUDITOR_TOOLS = [
    list_findings,
    get_scorecard,
    get_claim_facts,
    *CONTEXT_TOOLS,
    write_up_finding,
]
