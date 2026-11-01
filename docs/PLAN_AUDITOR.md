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

- [ ] `data/handlers.json` has the manager, and `can_audit` on every handler
- [ ] `npm run seed:audit` adds the ring, the second senior handler and the decoys
- [ ] Every scenario claim reads through the app's claim view
- [ ] Evaluation sets and the dispatch's waiting claims are untouched

## Phase 2: the backend

- [ ] Each check finds its planted pattern and no decoy, in tests
- [ ] Only the manager can read or act; the agent's key is refused
- [ ] No route gives the Auditor a story, a document, a reason, a note or contact details
- [ ] An explanation with a number outside the evidence, or an accusing word, is refused
- [ ] The manager can't decide a finding about themselves

## Phase 3: the agent

- [ ] The graph explains, pauses, and resumes on a freshly built graph with nothing redone
- [ ] A dismissal is remembered, and a later audit sets the pattern aside
- [ ] The sign-in is never saved, and the agent's key never sent
- [ ] A model call limit or a refused explanation still ends with the code's line
- [ ] The app answers `{"operation": "health"}`

## Phase 4: the dashboard

- [ ] An Audit page for the manager, and a refusal for anyone else
- [ ] Scorecard, findings, evidence and the decision card, in light and dark
- [ ] Vitest and end-to-end tests

## Phase 5: the live run

- [ ] A real audit on Supabase with a restart during the pause
- [ ] Results reported against every target in `docs/AUDITOR.md`
- [ ] `docs/` describe the product as it now is
