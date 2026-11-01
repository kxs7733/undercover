"""The Auditor's six checks, worked out in code from our records with no model: repeat
claimants, linked claimants, payouts just under the limit, send-backs that raised a
payout, sign-off patterns and third claims paid without referral. Each is a pure
function on a ledger of records, and says only what the records show: a pattern for
review, never an accusation. A link between customers says its kind, never the phone
or address it rests on."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from backend.models import DecisionKind

REPEAT_CLAIMANT = "repeat_claimant"
LINKED_CLAIMANTS = "linked_claimants"
UNDER_LIMIT = "under_limit"
SEND_BACK_RAISES = "send_back_raises"
SIGN_OFF_PATTERN = "sign_off_pattern"
THIRD_CLAIM_UNREFERRED = "third_claim_unreferred"

# A pattern is too small to raise below these.
FEWEST_REPEAT_APPROVALS = 3
FEWEST_LINKED_APPROVALS = 3
FEWEST_UNDER_LIMIT = 2
FEWEST_RAISES = 2
FEWEST_PATTERN_SIGN_OFFS = 3
THIRD_CLAIM = 3
TWELVE_MONTHS = timedelta(days=365)
# Just under the limit is within 10% of it.
UNDER_LIMIT_BAND = 0.9
# A sign-off this soon after the decision leaves no time to read it.
QUICK_SECONDS = 60
# A finding at or above this score waits for the manager's decision.
DECISION_SCORE = 70
BEST_SCORE = 100
SHARED_PHONE, SHARED_ADDRESS, SHARED_TRAVELER = (
    "shared_phone",
    "shared_address",
    "shared_traveler",
)


@dataclass(frozen=True)
class LedgerClaim:
    """A claim the agent decided, as the checks read it."""

    claim_id: str
    customer_id: str
    submitted_on: str
    decision: str
    payout: float
    paid: float | None
    decided_at: str
    signed_off_by: str | None
    signed_off_at: str | None
    approval_limit: float


@dataclass(frozen=True)
class LedgerSendBack:
    """A decision a handler sent back, with who sent it."""

    claim_id: str
    decision: str
    payout: float
    sent_back_by: str


@dataclass(frozen=True)
class Ledger:
    """Everything the checks read: the queue's decided claims, the day each of a
    customer's queue claims was filed, decided or not, the decisions sent back, each
    customer's record, each policy's record and the approval limit now."""

    claims: list[LedgerClaim]
    filed: dict[str, list[str]]
    sent_back: list[LedgerSendBack]
    customers: dict[str, dict[str, Any]]
    policies: list[dict[str, Any]]
    limit: float


@dataclass(frozen=True)
class Draft:
    """What a check found: its kind, its subject and how the subject reads, a risk
    score, the claims it rests on, the dollars paid on them, and the evidence."""

    check: str
    subject: str
    subject_name: str
    score: int
    claim_ids: list[str]
    exposure: float
    evidence: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        """What stays the same for this pattern from one audit to the next, while
        its subject does."""
        return f"{self.check}:{self.subject}"

    def needs_decision(self, limit: float) -> bool:
        """Say whether the manager must decide it: a high score, or more paid than
        the approval limit."""
        return self.score >= DECISION_SCORE or self.exposure > limit


def scored(points: int) -> int:
    return min(points, BEST_SCORE)


def paid_on(claims: list[LedgerClaim]) -> float:
    return round(sum(claim.paid or 0 for claim in claims), 2)


def approved(claims: list[LedgerClaim]) -> list[LedgerClaim]:
    return [claim for claim in claims if claim.decision == DecisionKind.APPROVE]


def ids_of(claims: list[LedgerClaim]) -> list[str]:
    return sorted(claim.claim_id for claim in claims)


def by_customer(claims: list[LedgerClaim]) -> dict[str, list[LedgerClaim]]:
    theirs: dict[str, list[LedgerClaim]] = defaultdict(list)
    for claim in claims:
        theirs[claim.customer_id].append(claim)
    return theirs


def links_between(ledger: Ledger) -> list[tuple[str, str, str]]:
    """Each pair of customers linked by a phone, an address or a traveler's name,
    with the link's kind."""
    keys: dict[tuple[str, str], list[str]] = defaultdict(list)
    named: dict[str, str] = {}
    for customer_id, record in ledger.customers.items():
        keys[SHARED_PHONE, record["phone"]].append(customer_id)
        address = record["address"]
        place = "|".join((address["street"], address["city"], address["zip"]))
        keys[SHARED_ADDRESS, place].append(customer_id)
        named[record["name"]] = customer_id
    links = [
        (kind, sorted(ids)[0], other)
        for (kind, _), ids in keys.items()
        for other in sorted(ids)[1:]
    ]
    for policy in ledger.policies:
        for traveler in policy["travelers"]:
            other = named.get(traveler)
            if other and other != policy["customer_id"]:
                pair = sorted((policy["customer_id"], other))
                links.append((SHARED_TRAVELER, pair[0], pair[1]))
    return links


def linked_groups(ledger: Ledger) -> list[tuple[list[str], list[str]]]:
    """The groups of customers joined by links, each with the kinds of link that
    join it."""
    parent = {customer_id: customer_id for customer_id in ledger.customers}

    def root(customer_id: str) -> str:
        while parent[customer_id] != customer_id:
            customer_id = parent[customer_id]
        return customer_id

    links = links_between(ledger)
    for _, one, other in links:
        parent[root(other)] = root(one)
    members: dict[str, list[str]] = defaultdict(list)
    for customer_id in ledger.customers:
        members[root(customer_id)].append(customer_id)
    return [
        (
            sorted(group),
            sorted({kind for kind, one, _ in links if one in group}),
        )
        for group in members.values()
        if len(group) > 1
    ]


def group_key(group: list[str]) -> str:
    return "+".join(group)


def names_of(ledger: Ledger, customer_ids: list[str]) -> str:
    return ", ".join(ledger.customers[c]["name"] for c in customer_ids)


def linked_claimants(ledger: Ledger) -> list[Draft]:
    """Groups of linked customers with several approvals between them."""
    theirs = by_customer(approved(ledger.claims))
    drafts = []
    for group, kinds in linked_groups(ledger):
        claims = [claim for c in group for claim in theirs.get(c, [])]
        if len(claims) < FEWEST_LINKED_APPROVALS:
            continue
        evidence = {
            "customers": len(group),
            "approvals": len(claims),
            "paid": paid_on(claims),
            "link_kinds": kinds,
        }
        drafts.append(
            Draft(
                LINKED_CLAIMANTS,
                group_key(group),
                names_of(ledger, group),
                scored(40 + 8 * len(claims) + 20 * (len(kinds) > 1)),
                ids_of(claims),
                paid_on(claims),
                evidence,
            )
        )
    return drafts


def under_limit(ledger: Ledger) -> list[Draft]:
    """Payouts just under the approval limit, clustered on one customer or one group
    of linked customers."""
    band = [
        claim
        for claim in approved(ledger.claims)
        if claim.approval_limit * UNDER_LIMIT_BAND
        <= claim.payout
        < claim.approval_limit
    ]
    theirs = by_customer(band)
    groups = [group for group, _ in linked_groups(ledger)]
    grouped = {c for group in groups for c in group}
    alone = [[c] for c in theirs if c not in grouped]
    drafts = []
    for group in [*groups, *alone]:
        claims = [claim for c in group for claim in theirs.get(c, [])]
        if len(claims) < FEWEST_UNDER_LIMIT:
            continue
        evidence = {
            "payouts_just_under": len(claims),
            "approval_limit": max(c.approval_limit for c in claims),
            "lowest": min(c.payout for c in claims),
            "highest": max(c.payout for c in claims),
            "paid": paid_on(claims),
        }
        drafts.append(
            Draft(
                UNDER_LIMIT,
                group_key(group),
                names_of(ledger, group),
                scored(40 + 10 * len(claims)),
                ids_of(claims),
                paid_on(claims),
                evidence,
            )
        )
    return drafts


def day_of(moment: str) -> date:
    return date.fromisoformat(moment[:10])


def most_within_a_year(days: list[date], ends: list[date]) -> int:
    """The most of these days in the twelve months up to any of the days given, so a
    pattern always reaches a claim in the queue."""
    return max(
        (sum(end - TWELVE_MONTHS <= day <= end for day in days) for end in ends),
        default=0,
    )


def repeat_claimant(ledger: Ledger) -> list[Draft]:
    """Customers with several approvals within twelve months, earlier ones
    included."""
    drafts = []
    for customer_id, claims in by_customer(approved(ledger.claims)).items():
        earlier = [
            earlier["filed_on"]
            for earlier in ledger.customers[customer_id]["previous_claims"]
            if earlier["outcome"] == "approved"
        ]
        ends = [day_of(c.submitted_on) for c in claims]
        most = most_within_a_year([*map(day_of, earlier), *ends], ends)
        if most < FEWEST_REPEAT_APPROVALS:
            continue
        evidence = {"approvals_in_twelve_months": most, "paid": paid_on(claims)}
        drafts.append(
            Draft(
                REPEAT_CLAIMANT,
                customer_id,
                names_of(ledger, [customer_id]),
                scored(30 + 15 * most),
                ids_of(claims),
                paid_on(claims),
                evidence,
            )
        )
    return drafts


def filed_before(ledger: Ledger, claim: LedgerClaim) -> int:
    """How many of the customer's claims were filed in the twelve months up to this
    one, counting it and every outcome, open ones included, as claims manual section
    9 does."""
    customer = ledger.customers[claim.customer_id]
    filed = [earlier["filed_on"] for earlier in customer["previous_claims"]]
    filed += ledger.filed.get(claim.customer_id, [])
    day = day_of(claim.submitted_on)
    return sum(day - TWELVE_MONTHS <= day_of(f) <= day for f in filed)


def third_claim_unreferred(ledger: Ledger) -> list[Draft]:
    """A third claim in twelve months paid with no referral, which claims manual
    section 9 asks for before payment."""
    drafts = []
    for claim in approved(ledger.claims):
        count = filed_before(ledger, claim)
        if count < THIRD_CLAIM or claim.paid is None:
            continue
        evidence = {
            "claims_in_twelve_months": count,
            "paid": claim.paid,
            "manual_section": 9,
        }
        drafts.append(
            Draft(
                THIRD_CLAIM_UNREFERRED,
                claim.claim_id,
                names_of(ledger, [claim.customer_id]),
                80,
                [claim.claim_id],
                claim.paid,
                evidence,
            )
        )
    return drafts


def send_back_raises(ledger: Ledger) -> list[Draft]:
    """A handler whose send-backs keep ending in a higher payout, counting a claim
    once from the lowest payout they sent back on it."""
    claims = {claim.claim_id: claim for claim in ledger.claims}
    lowest: dict[tuple[str, str], float] = {}
    for earlier in ledger.sent_back:
        key = (earlier.sent_back_by, earlier.claim_id)
        lowest[key] = min(earlier.payout, lowest.get(key, earlier.payout))
    raises: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (handler, claim_id), before in lowest.items():
        now = claims.get(claim_id)
        if now and now.decision == DecisionKind.APPROVE and now.payout > before:
            raises[handler].append(
                {"claim_id": claim_id, "before": before, "after": now.payout}
            )
    drafts = []
    for handler, raised in raises.items():
        if len(raised) < FEWEST_RAISES:
            continue
        added = round(sum(r["after"] - r["before"] for r in raised), 2)
        paid = paid_on([claims[r["claim_id"]] for r in raised])
        drafts.append(
            Draft(
                SEND_BACK_RAISES,
                handler,
                handler,
                scored(50 + 15 * len(raised)),
                sorted(r["claim_id"] for r in raised),
                paid,
                {"raises": len(raised), "added": added, "paid": paid, "each": raised},
            )
        )
    return drafts


def seconds_to_sign_off(claim: LedgerClaim) -> float:
    signed = datetime.fromisoformat(claim.signed_off_at or claim.decided_at)
    return (signed - datetime.fromisoformat(claim.decided_at)).total_seconds()


def sign_off_pattern(ledger: Ledger) -> list[Draft]:
    """A handler who keeps signing off quickly, or keeps signing off one group of
    linked customers."""
    signed: dict[str, list[LedgerClaim]] = defaultdict(list)
    for claim in ledger.claims:
        if claim.signed_off_by:
            signed[claim.signed_off_by].append(claim)
    groups = [set(group) for group, _ in linked_groups(ledger)]
    drafts = []
    for handler, claims in signed.items():
        quick = [c for c in claims if seconds_to_sign_off(c) < QUICK_SECONDS]
        same_group = max(
            (sum(c.customer_id in group for c in claims) for group in groups),
            default=0,
        )
        if max(len(quick), same_group) < FEWEST_PATTERN_SIGN_OFFS:
            continue
        paid = paid_on(claims)
        evidence = {
            "sign_offs": len(claims),
            "quick_sign_offs": len(quick),
            "most_for_one_linked_group": same_group,
            "median_seconds": median(seconds_to_sign_off(c) for c in claims),
            "paid": paid,
        }
        drafts.append(
            Draft(
                SIGN_OFF_PATTERN,
                handler,
                handler,
                scored(50 + 10 * max(len(quick), same_group)),
                ids_of(claims),
                paid,
                evidence,
            )
        )
    return drafts


CHECKS = (
    linked_claimants,
    under_limit,
    repeat_claimant,
    third_claim_unreferred,
    send_back_raises,
    sign_off_pattern,
)


def run_checks(ledger: Ledger) -> list[Draft]:
    """Every pattern the checks find, the highest score first."""
    drafts = [draft for check in CHECKS for draft in check(ledger)]
    return sorted(drafts, key=lambda d: (-d.score, d.fingerprint))
