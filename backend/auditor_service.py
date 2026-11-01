"""The Auditor, as the app calls it: an audit, or the manager's answer on a finding,
posted to its AgentCore app on the laptop, with no key, since the payload carries the
manager's sign-in."""

import os

import httpx

from backend import runtime_calls
from backend.runtime_calls import Wording

AUDITOR = "UNDERCOVER_AUDITOR"
# The Auditor's AgentCore app on the laptop, as npm run dev serves it.
LOCAL_AUDITOR = "http://127.0.0.1:8082"
NOT_RUNNING = "The Auditor isn't running"
NO_ANSWER = (
    "The Auditor didn't answer in time. Reload the page to see whether it went through."
)
COULDNT_TAKE = "The Auditor couldn't take the audit: {reason}"
WORDING = Wording(NOT_RUNNING, COULDNT_TAKE, NO_ANSWER)

auditor = httpx.Client()


def ask(operation: str, audit_id: str, sign_in: str) -> None:
    """Ask the Auditor to work on an audit, as the manager signed in. Raise NotTaken
    or MayHaveStarted when it didn't, or may not have."""
    payload = {"operation": operation, "audit_id": audit_id, "sign_in": sign_in}
    url = os.getenv(AUDITOR, LOCAL_AUDITOR)
    runtime_calls.post(auditor, url, payload, {}, WORDING)
