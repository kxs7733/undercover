# Plan: the Auditor

Builds `docs/AUDITOR.md`.

## Design

- `data/audit/`: the planted scenario and its answer key.
- `backend/audit_seed.py`: adds the scenario to a seeded database.
- `backend/audit_checks.py`: the six checks, pure functions on a ledger of records.
- `backend/audit_writeups.py`: the code's check of an explanation.
- `backend/audits.py`: the manager's routes; `backend/auditor_service.py`: how the app asks the Auditor.
- `agent/auditor/`: `app_api.py` (its only way to the app), `tools.py`, `memory.py`, `graph.py`, `work.py`, `entrypoint.py`, `instructions.md`.
- `dashboard/src/pages/AuditPage.tsx`: the page, for the manager only.

The auditor uses, of the rest of the agent, only the shared modules the Copilot uses.

## Phase 1: the planted scenario

- [x] `data/handlers.json` has the manager, and `can_audit` on every handler
- [x] `npm run seed:audit` adds the ring, the second senior handler and the decoys
- [x] Every scenario claim reads through the app's claim view
- [x] Evaluation sets and the dispatch's waiting claims are untouched

## Phase 2: the backend

- [x] Each check finds its planted pattern and no decoy, in tests
- [x] Only the manager can read or act; the agent's key is refused
- [x] No route gives the Auditor a story, a document, a reason, a note or contact details
- [x] An explanation with a number outside the evidence, or an accusing word, is refused
- [x] The manager can't decide a finding about themselves

## Phase 3: the agent

- [x] The graph explains, pauses, and resumes on a freshly built graph with nothing redone
- [x] A dismissal is remembered, and a later audit sets the pattern aside
- [x] The sign-in is never saved, and the agent's key never sent
- [x] A model call limit or a refused explanation still ends with the code's line
- [x] The app answers `{"operation": "health"}`

## Phase 4: the dashboard

- [x] An Audit page for the manager, and a refusal for anyone else
- [x] Scorecard, findings, evidence and the decision card, in light and dark
- [x] Vitest and end-to-end tests

## Phase 5: the live run

- [x] A real audit on Supabase with a restart during the pause
- [x] Results reported against every target in `docs/AUDITOR.md`
- [x] `docs/` describe the product as it now is
