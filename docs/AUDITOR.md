# The UnderCover Auditor

The capstone's extension, a local build. A claims operations manager needs to judge how accurately the claim agent handles claims, and to see patterns across claims that nobody deciding one claim can see, such as repeated lenient approvals for the same or linked claimants.

## What we want

- **A manager role.** A new handler, the claims operations manager, can audit. Nobody else can, and the manager can't decide a finding about themselves.
- **Code finds, the model explains.** Seven things are worked out in code from our records: a scorecard of each agent version's accuracy and leniency, and six checks: repeat claimants, linked claimants, payouts just under the limit, send-backs that raised a payout, sign-off patterns and third claims paid without referral. The model never sets a score, an amount or a finding.
- **The model only writes the explanation,** and each one is checked in code: every number must be in the finding's evidence, and accusing words are refused. A refused explanation goes back to the model; a finding it never explains keeps a line written in code.
- **It never accuses.** Claims manual section 8 forbids it. A finding is a pattern for review. A case goes to the Special Investigations Unit only when the manager confirms it. Nothing is said to a customer, held or paid.
- **It reads no customer's words.** The Auditor sees structured records only: no story, no document, no reason and no note, so a claim can't talk it out of a finding. It also never sees a customer's email, phone, address or date of birth; a link says only its kind.
- **Handlers' decisions stay out of reach.** On the labeled sets the Auditor gets only figures across a version's evaluations, never a decision on a claim.
- **It asks before it opens a case.** A finding with a risk score of 70 or more, or paid more than the approval limit, pauses the audit in a LangGraph `interrupt()` until the manager opens a case or dismisses it, with a reason. The pause survives a restart.
- **It remembers each manager's dismissals,** in a `PostgresStore` on Supabase, by a fingerprint of the check and its subject. The same pattern isn't raised again unless its subject changes.

## How it runs

With no AWS. The Auditor is an AgentCore app of its own on 127.0.0.1:8082 with `npm run dev`, built like the Copilot, a hand-written `StateGraph` with a `PostgresSaver`, working with the manager's sign-in and never the agent's key, with at most 2 database connections, since Supabase's free plan allows 15. It is not deployed to AgentCore Runtime: on the course's free route it runs on Render as a fourth free web service, from `render.yaml`, beside the app, the agent and the Copilot, with the same Supabase database.

`npm run seed:audit` adds a planted scenario to a seeded database, with its answer key in `data/audit/planted.json`, which nothing in the product reads.

## Success targets, set before the build

| Measure                                                  | Target                            |
| -------------------------------------------------------- | --------------------------------- |
| Planted patterns found                                   | All of them                       |
| Decoys wrongly flagged                                   | At most 1                         |
| Figures written by the model that aren't in the evidence | 0                                 |
| Accusing words, or contact details reaching the model    | 0                                 |
| An injected story changes the result                     | Never                             |
| A pause survives a restart with nothing redone           | Yes                               |
| Cost of an audit                                         | Under $0.50                       |
| `npm run check`                                          | Green, with `TZ=America/New_York` |

## Not for now

- Deploying the Auditor to AgentCore Runtime.
- Holding or stopping a payment, or anything sent to a customer.
- The Auditor in the Copilot's sidebar.
