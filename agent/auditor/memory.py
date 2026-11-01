"""What the Auditor remembers of each manager: the patterns they dismissed, with
why and on which claims, kept in a PostgresStore on Supabase under the manager's id,
by the pattern's fingerprint. One manager's dismissals are never used for another."""

from typing import Any

from langgraph.store.base import BaseStore

MANAGERS = "managers"
DISMISSALS = "dismissals"


def namespace(manager_id: str) -> tuple[str, str, str]:
    return (MANAGERS, manager_id, DISMISSALS)


def dismissed_before(
    store: BaseStore, manager_id: str, fingerprint: str
) -> dict[str, Any] | None:
    """What this manager said when they dismissed this pattern, if they did."""
    found = store.get(namespace(manager_id), fingerprint)
    return found.value if found else None


def remember_dismissal(
    store: BaseStore,
    manager_id: str,
    fingerprint: str,
    reason: str,
    claim_ids: list[str],
) -> None:
    store.put(
        namespace(manager_id), fingerprint, {"reason": reason, "claim_ids": claim_ids}
    )
