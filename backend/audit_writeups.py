"""The code's check of what the model writes on a finding: every number in it must
be in the finding's evidence, and it may not accuse anyone, as claims manual section
8 says. It also holds the line a finding keeps when the model never explains it."""

import json
import re
from typing import Any

from backend import audit_checks

# A section of a document, and the twelve months of claims manual section 9, are
# names, not figures. A claim's id is checked against the finding's.
NAMES = re.compile(
    r"\b(?:CUS|POL|HND)-\d+\b"
    r"|\bsections?\s+\d{1,2}(?:\s*(?:,|and|&)\s*\d{1,2})*\b"
    r"|\b12[- ]months?\b",
    re.IGNORECASE,
)
CLAIM_ID = re.compile(r"\bCLM-\d+\b", re.IGNORECASE)
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# A large figure in words dodges the check of figures, so none may stand.
FIGURE_IN_WORDS = re.compile(r"\b(hundred|thousand|million|billion)s?\b", re.IGNORECASE)
ACCUSING = re.compile(
    r"\b(\w*fraud\w*|scam\w*|crimin\w*|dishonest\w*|lied|lying|liar\w*|cheat\w*"
    r"|corrupt\w*|collu\w*|kickback\w*|embezzl\w*|guilty|deliberate\w*"
    r"|intentional\w*|on purpose|staged|fabricat\w*|faked?|forge\w*)\b",
    re.IGNORECASE,
)
NEW_FIGURE = (
    "It gives figures that aren't in the evidence: {figures}. "
    "Use only the evidence's figures."
)
ACCUSES = (
    "It uses words that accuse someone. "
    "Describe the pattern for review, as claims manual section 8 asks."
)
OTHER_CLAIMS = "It names claims outside this finding: {claims}."
IN_WORDS = "It gives a figure in words. Use only the evidence's figures, as digits."

LINES = {
    audit_checks.REPEAT_CLAIMANT: (
        "Several approvals for one customer within twelve months, for review."
    ),
    audit_checks.LINKED_CLAIMANTS: (
        "Several approvals across customers linked in our records, for review."
    ),
    audit_checks.UNDER_LIMIT: (
        "Several payouts just under the approval limit on one customer or linked "
        "group, for review."
    ),
    audit_checks.SEND_BACK_RAISES: (
        "Several decisions sent back by one handler ended in a higher payout, "
        "for review."
    ),
    audit_checks.SIGN_OFF_PATTERN: (
        "One handler's sign-offs were quick, or concentrated on one linked group, "
        "for review."
    ),
    audit_checks.THIRD_CLAIM_UNREFERRED: (
        "A third claim in twelve months was paid without the referral claims "
        "manual section 9 asks for, for review."
    ),
}


def value_of(number: str) -> float:
    return float(number.replace(",", ""))


def numbers_in(text: str) -> set[float]:
    return {
        round(value_of(n.rstrip(",")), 2)
        for n in NUMBER.findall(CLAIM_ID.sub(" ", NAMES.sub(" ", text)))
    }


def why_refused(
    narrative: str, evidence: dict[str, Any], claim_ids: list[str]
) -> str | None:
    """Say why an explanation can't stand, if it can't: an accusing word, a claim
    outside the finding, a figure in words, or a number the evidence doesn't hold."""
    if ACCUSING.search(narrative):
        return ACCUSES
    named = {c.upper() for c in CLAIM_ID.findall(narrative)}
    if others := named - set(claim_ids):
        return OTHER_CLAIMS.format(claims=", ".join(sorted(others)))
    if FIGURE_IN_WORDS.search(narrative):
        return IN_WORDS
    # $1,180.00 and 1180 are one figure.
    new = numbers_in(narrative) - numbers_in(json.dumps(evidence))
    if new:
        return NEW_FIGURE.format(figures=", ".join(f"{n:g}" for n in sorted(new)))
    return None
