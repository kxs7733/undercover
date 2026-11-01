import { ShieldAlert } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import {
  type Audit,
  type AuditFinding,
  CHECK_TITLES,
  evidenceRows,
  FINDING_LABELS,
  type FindingAnswer,
  isWorking,
  type Scorecard,
} from "../audit";
import { ClaimLink } from "../components/ClaimLink";
import { FormError } from "../components/FormError";
import { PageHeader } from "../components/PageHeader";
import { StateMessage } from "../components/StateMessage";
import { dateTime, modelCost, money, percent } from "../format";
import { useHandler } from "../handler";
import { useAction } from "../useAction";
import { REFRESH_MS, useLoad } from "../useLoad";

const THE_RULE =
  "Patterns across claims, for review. They aren't accusations: many turn out to be innocent, and nothing here is said to a customer or stops a payment.";

export function AuditPage() {
  const handler = useHandler();
  if (!handler.can_audit)
    return (
      <>
        <PageHeader title="Audit" />
        <p className="not-allowed">
          Only the claims operations manager can audit. {handler.name} can't.
        </p>
      </>
    );
  return <ManagerAudit />;
}

function ManagerAudit() {
  const audits = useLoad(api.listAudits, REFRESH_MS, isWorking);
  const scorecard = useLoad(api.getAuditScorecard);
  const start = useAction(api.startAudit);
  const latest = audits.data?.[0];
  const going =
    latest?.status === "working" || latest?.status === "waiting_for_decision";
  return (
    <>
      <PageHeader
        title="Audit"
        lead={THE_RULE}
        action={
          <button
            type="button"
            className="button"
            aria-disabled={going || start.sending}
            onClick={() => {
              if (!going)
                void start.run().finally(() => {
                  audits.reload();
                });
            }}
          >
            <ShieldAlert aria-hidden />
            Start an audit
          </button>
        }
      />
      {start.error && <FormError>{start.error}</FormError>}
      {scorecard.data ? (
        <ScorecardPanels card={scorecard.data} />
      ) : (
        <StateMessage error={scorecard.error} />
      )}
      {audits.data ? (
        <LatestOrNone
          audit={latest}
          onAnswered={() => {
            audits.reload();
          }}
        />
      ) : (
        <StateMessage error={audits.error} />
      )}
    </>
  );
}

function LatestOrNone({
  audit,
  onAnswered,
}: Readonly<{ audit?: Audit; onAnswered: () => void }>) {
  if (!audit)
    return (
      <StateMessage empty="No audit yet. Start one to check our records." />
    );
  return <LatestAudit audit={audit} onAnswered={onAnswered} />;
}

function ScorecardPanels({ card }: Readonly<{ card: Scorecard }>) {
  return (
    <>
      <section className="panel audit-panel" aria-label="Agent versions">
        <h2>Agent versions</h2>
        {card.versions.length === 0 ? (
          <p className="muted">No evaluation has finished yet.</p>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Version</th>
                  <th>Claims evaluated</th>
                  <th>Accuracy</th>
                  <th>More lenient than a handler</th>
                  <th>Stricter than a handler</th>
                  <th>Overpaid</th>
                </tr>
              </thead>
              <tbody>
                {card.versions.map((version) => (
                  <tr key={version.version}>
                    <td>{version.version}</td>
                    <td>{version.claims}</td>
                    <td>{percent(version.accuracy)}</td>
                    <td>{percent(version.lenient_share)}</td>
                    <td>{percent(version.strict_share)}</td>
                    <td>{money(version.overpaid)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="panel audit-panel" aria-label="Handlers">
        <h2>Handlers</h2>
        {card.handlers.length === 0 ? (
          <p className="muted">No sign-off or send-back yet.</p>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Handler</th>
                  <th>Sign-offs</th>
                  <th>Paid</th>
                  <th>Signed off within a minute</th>
                  <th>Send-backs</th>
                  <th>Ended higher</th>
                </tr>
              </thead>
              <tbody>
                {card.handlers.map((handler) => (
                  <tr key={handler.name}>
                    <td>{handler.name}</td>
                    <td>{handler.sign_offs}</td>
                    <td>{money(handler.paid)}</td>
                    <td>{handler.quick_sign_offs}</td>
                    <td>{handler.send_backs}</td>
                    <td>{handler.raised}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

function LatestAudit({
  audit,
  onAnswered,
}: Readonly<{ audit: Audit; onAnswered: () => void }>) {
  return (
    <section aria-label="Latest audit">
      <div className="panel audit-panel" aria-live="polite">
        <h2>Latest audit</h2>
        <p>
          Started by {audit.started_by} on {dateTime(audit.started_at)}.{" "}
          {audit.status === "working" && "The Auditor is working."}
          {audit.status === "waiting_for_decision" &&
            "It's waiting for your decision."}
        </p>
        {audit.summary && <p>{audit.summary}</p>}
        {audit.failure && <p role="alert">{audit.failure}</p>}
        <p className="muted small">
          {audit.model_calls} model calls, {modelCost(audit.cost)}.
        </p>
      </div>
      {audit.findings.length === 0 && (
        <StateMessage empty="The checks found no pattern for review." />
      )}
      {audit.findings.map((finding) => (
        <FindingCard
          key={finding.finding_id}
          finding={finding}
          waiting={audit.waiting_on === finding.finding_id}
          onAnswered={onAnswered}
        />
      ))}
      {audit.steps.length > 0 && (
        <details className="panel audit-panel">
          <summary>The Auditor's steps ({audit.steps.length})</summary>
          <ol className="audit-steps">
            {audit.steps.map((step) => (
              <li key={step.step_id}>
                <span className="mono">{step.tool}</span> {step.input}{" "}
                <span className="muted">({step.status})</span>
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}

function FindingCard({
  finding,
  waiting,
  onAnswered,
}: Readonly<{
  finding: AuditFinding;
  waiting: boolean;
  onAnswered: () => void;
}>) {
  const title = CHECK_TITLES[finding.check_name] ?? finding.check_name;
  const handler = useHandler();
  const aboutYou =
    finding.status === "open" && finding.subject === handler.name;
  return (
    <article
      className={`panel audit-panel audit-finding${waiting ? " waiting" : ""}`}
      aria-label={`${title}: ${finding.subject_name}`}
    >
      <header className="audit-finding-head">
        <h3>{title}</h3>
        <span className="chip">{FINDING_LABELS[finding.status]}</span>
        <span className="chip">Risk score {finding.score}</span>
      </header>
      <p>
        <strong>{finding.subject_name}</strong>, with{" "}
        <span className="mono">{money(finding.exposure)}</span> paid.
      </p>
      <p>{finding.narrative}</p>
      <dl className="audit-evidence">
        {evidenceRows(finding.evidence).map(([name, value]) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd className="mono">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="audit-claims">
        {finding.claim_ids.map((claimId) => (
          <ClaimLink key={claimId} claimId={claimId} />
        ))}
      </p>
      {finding.answer_reason && (
        <p className="muted small">
          {finding.answered_by ? `${finding.answered_by}: ` : ""}
          {finding.answer_reason}
        </p>
      )}
      {aboutYou && (
        <p className="not-allowed">
          This finding is about you, so someone else must decide it.
        </p>
      )}
      {waiting && <Decision finding={finding} onAnswered={onAnswered} />}
    </article>
  );
}

function Decision({
  finding,
  onAnswered,
}: Readonly<{ finding: AuditFinding; onAnswered: () => void }>) {
  const [reason, setReason] = useState("");
  const answer = useAction((given: FindingAnswer) =>
    api.answerFinding(finding.audit_id, finding.finding_id, given, reason),
  );
  const ready = reason.trim() !== "" && !answer.sending;
  function send(given: FindingAnswer) {
    // Reloads whatever came back: a timed-out answer may have gone through.
    if (ready)
      void answer.run(given).finally(() => {
        onAnswered();
      });
  }
  return (
    <div className="audit-decision">
      <label>
        Why
        <textarea
          rows={2}
          maxLength={500}
          value={reason}
          onChange={(event) => {
            setReason(event.target.value);
          }}
        />
      </label>
      <p className="muted small">Say why to open a case or dismiss it.</p>
      <div className="audit-decision-buttons">
        <button
          type="button"
          className="button"
          aria-disabled={!ready}
          onClick={() => {
            send("open_case");
          }}
        >
          Open a case
        </button>
        <button
          type="button"
          className="button quiet"
          aria-disabled={!ready}
          onClick={() => {
            send("dismiss");
          }}
        >
          Dismiss
        </button>
      </div>
      {answer.error && <FormError>{answer.error}</FormError>}
    </div>
  );
}
