"""The UnderCover backend's API for the Auditor: one function for each operation it
uses, each taking the manager's sign-in first and sending it, never the agent's key.
It has no way to a customer's words or contact details, or a handler's decision on a
labeled claim."""

from typing import Any, TypedDict

from agent import connection
from agent.connection import call_as

# The app's refusal of a request, which each function raises.
Refused = connection.Refused
# An audit's and a finding's states, as the app records them.
WORKING = "working"
OPEN = "open"
DISMISSED = "dismissed"


def get_signed_in_handler(sign_in: str) -> dict[str, Any]:
    return call_as(sign_in, "GET", "/me")


def get_model(sign_in: str) -> dict[str, Any]:
    return call_as(sign_in, "GET", "/copilot/model")


def get_audit(sign_in: str, audit_id: str) -> dict[str, Any]:
    return call_as(sign_in, "GET", f"/audits/{audit_id}")


def get_scorecard(sign_in: str) -> dict[str, Any]:
    return call_as(sign_in, "GET", "/audit-scorecard")


def get_claim(sign_in: str, claim_id: str) -> dict[str, Any]:
    return call_as(sign_in, "GET", f"/audit-claims/{claim_id}")


def write_up(
    sign_in: str, audit_id: str, finding_id: int, narrative: str
) -> dict[str, Any]:
    path = f"/audits/{audit_id}/findings/{finding_id}/write-up"
    return call_as(sign_in, "POST", path, json={"narrative": narrative})


def set_aside(
    sign_in: str, audit_id: str, finding_id: int, reason: str
) -> dict[str, Any]:
    path = f"/audits/{audit_id}/findings/{finding_id}/set-aside"
    return call_as(sign_in, "POST", path, json={"reason": reason})


class Step(TypedDict):
    """A step the Auditor took, as the manager's page shows it."""

    tool: str
    input: str
    status: str
    answer: str


def record_step(sign_in: str, audit_id: str, step: Step) -> dict[str, Any]:
    return call_as(sign_in, "POST", f"/audits/{audit_id}/steps", json=step)


def pause(
    sign_in: str, audit_id: str, finding_id: int, model_calls: int, cost: float
) -> dict[str, Any]:
    body = {"finding_id": finding_id, "model_calls": model_calls, "cost": cost}
    return call_as(sign_in, "POST", f"/audits/{audit_id}/pause", json=body)


def finish(
    sign_in: str, audit_id: str, model_calls: int, cost: float
) -> dict[str, Any]:
    body = {"model_calls": model_calls, "cost": cost}
    return call_as(sign_in, "POST", f"/audits/{audit_id}/finish", json=body)


def fail(sign_in: str, audit_id: str, reason: str) -> dict[str, Any]:
    body = {"reason": reason}
    return call_as(sign_in, "POST", f"/audits/{audit_id}/failure", json=body)
