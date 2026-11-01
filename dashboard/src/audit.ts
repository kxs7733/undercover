// An audit as the app gives it: what the checks found in code, with an explanation
// the code checked, and the steps the Auditor took.
export type AuditStatus =
  "working" | "waiting_for_decision" | "done" | "failed";
export type FindingStatus = "open" | "case_opened" | "dismissed" | "set_aside";
export type FindingAnswer = "open_case" | "dismiss";

export interface AuditFinding {
  finding_id: number;
  audit_id: string;
  check_name: string;
  subject: string;
  subject_name: string;
  fingerprint: string;
  score: number;
  needs_decision: boolean;
  claim_ids: string[];
  exposure: number;
  evidence: Record<string, unknown>;
  narrative: string;
  written_by_model: boolean;
  status: FindingStatus;
  answer_reason: string | null;
  answered_by: string | null;
  answered_at: string | null;
}

export interface AuditStep {
  step_id: number;
  audit_id: string;
  tool: string;
  input: string;
  status: string;
  answer: string;
  at: string;
}

export interface Audit {
  audit_id: string;
  started_by: string;
  status: AuditStatus;
  started_at: string;
  finished_at: string | null;
  summary: string | null;
  failure: string | null;
  model_calls: number;
  cost: number;
  waiting_on: number | null;
  findings: AuditFinding[];
  steps: AuditStep[];
}

export interface VersionLens {
  version: number;
  evaluations: number;
  claims: number;
  accuracy: number;
  lenient_share: number;
  strict_share: number;
  overpaid: number;
}

export interface HandlerLens {
  name: string;
  sign_offs: number;
  paid: number;
  quick_sign_offs: number;
  send_backs: number;
  raised: number;
}

export interface Scorecard {
  versions: VersionLens[];
  handlers: HandlerLens[];
}

export const CHECK_TITLES: Record<string, string> = {
  repeat_claimant: "Repeat claimant",
  linked_claimants: "Linked claimants",
  under_limit: "Payouts just under the limit",
  send_back_raises: "Send-backs that raised a payout",
  sign_off_pattern: "Sign-off pattern",
  third_claim_unreferred: "Third claim paid without referral",
};

export const FINDING_LABELS: Record<FindingStatus, string> = {
  open: "For review",
  case_opened: "Case opened",
  dismissed: "Dismissed",
  set_aside: "Dismissed before",
};

// Whether an audit is still going, so the page keeps asking how it stands. A wait
// for the manager's decision needs no asking until they answer.
export function isWorking(audits: Audit[]): boolean {
  return audits.some((audit) => audit.status === "working");
}

// An evidence value as the page shows it, leaving out what a finding's other
// parts already show. Lists of links read as words.
export function evidenceRows(
  evidence: Record<string, unknown>,
): [string, string][] {
  return Object.entries(evidence)
    .filter(([key]) => key !== "each")
    .map(([key, value]) => [
      key.replaceAll("_", " "),
      Array.isArray(value)
        ? value.map((item) => String(item).replaceAll("_", " ")).join(", ")
        : String(value),
    ]);
}
