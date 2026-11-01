import {
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Audit, Scorecard } from "./audit";
import { evidenceRows, isWorking } from "./audit";
import type { Handler } from "./api";
import { Refusal, marcus, renderAt, sent, stubApi } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

const elena: Handler = {
  handler_id: "HND-04",
  name: "Elena Marsh",
  role: "Claims Operations Manager",
  email: "elena.marsh@undercover.example",
  can_approve_over_limit: false,
  can_audit: true,
};

const scorecard: Scorecard = {
  versions: [
    {
      version: 1,
      evaluations: 1,
      claims: 5,
      accuracy: 0.8,
      lenient_share: 0.2,
      strict_share: 0,
      overpaid: 150,
    },
  ],
  handlers: [
    {
      name: "Jonah Albright",
      sign_offs: 3,
      paid: 3740,
      quick_sign_offs: 3,
      send_backs: 2,
      raised: 2,
    },
  ],
};

const finding = {
  finding_id: 7,
  audit_id: "audit-1",
  check_name: "send_back_raises",
  subject: "Jonah Albright",
  subject_name: "Jonah Albright",
  fingerprint: "send_back_raises:Jonah Albright",
  score: 80,
  needs_decision: true,
  claim_ids: ["CLM-7005", "CLM-7007"],
  exposure: 2420,
  evidence: { raises: 2, link_kinds: ["shared_phone"], each: [] },
  narrative: "Two send-backs ended in a higher payout, for review.",
  written_by_model: true,
  status: "open" as const,
  answer_reason: null,
  answered_by: null,
  answered_at: null,
};

const waiting: Audit = {
  audit_id: "audit-1",
  started_by: "Elena Marsh",
  status: "waiting_for_decision",
  started_at: "2026-11-01T08:00:00+00:00",
  finished_at: null,
  summary: null,
  failure: null,
  model_calls: 4,
  cost: 0.01,
  waiting_on: 7,
  findings: [finding],
  steps: [
    {
      step_id: 1,
      audit_id: "audit-1",
      tool: "list_findings",
      input: "{}",
      status: "done",
      answer: "[]",
      at: "2026-11-01T08:00:01+00:00",
    },
  ],
};

function asManager(audits: Audit[], more = {}) {
  return stubApi({
    "GET /api/me": elena,
    "GET /api/audits": audits,
    "GET /api/audit-scorecard": scorecard,
    ...more,
  });
}

it("tells anyone but the manager they can't audit, and offers no link", async () => {
  const fetchMock = stubApi({ "GET /api/me": marcus });
  renderAt("/audit");
  expect(
    await screen.findByText(
      "Only the claims operations manager can audit. Marcus Oyelaran can't.",
    ),
  ).toBeDefined();
  expect(screen.queryByRole("link", { name: "Audit" })).toBeNull();
  expect(sent(fetchMock, "GET /api/audits")).toHaveLength(0);
});

it("shows the manager the scorecard, a finding and its evidence, and a link", async () => {
  asManager([waiting]);
  renderAt("/audit");
  const versions = await screen.findByRole("region", {
    name: "Agent versions",
  });
  expect(within(versions).getByText("80%")).toBeDefined();
  const handlers = screen.getByRole("region", { name: "Handlers" });
  expect(within(handlers).getByText("Jonah Albright")).toBeDefined();
  const card = await screen.findByRole("article", {
    name: "Send-backs that raised a payout: Jonah Albright",
  });
  expect(within(card).getByText(finding.narrative)).toBeDefined();
  expect(within(card).getByText("Risk score 80")).toBeDefined();
  expect(within(card).getByText("shared phone")).toBeDefined();
  expect(within(card).getByRole("link", { name: "CLM-7005" })).toBeDefined();
  expect(screen.getByRole("link", { name: "Audit" })).toBeDefined();
  expect(screen.getByText("The Auditor's steps (1)")).toBeDefined();
});

it("asks for a reason, then sends the manager's decision", async () => {
  const fetchMock = asManager([waiting], {
    "POST /api/audits/audit-1/findings/7/answer": waiting,
  });
  renderAt("/audit");
  const open = await screen.findByRole("button", { name: "Open a case" });
  fireEvent.click(open);
  const route = "POST /api/audits/audit-1/findings/7/answer";
  expect(sent(fetchMock, route)).toHaveLength(0);
  fireEvent.change(screen.getByLabelText("Why"), {
    target: { value: "Worth a look" },
  });
  fireEvent.click(open);
  await waitFor(() => {
    expect(sent(fetchMock, route)).toEqual([
      { answer: "open_case", reason: "Worth a look" },
    ]);
  });
});

it("passes on a refusal of a decision", async () => {
  asManager([waiting], {
    "POST /api/audits/audit-1/findings/7/answer": new Refusal(
      403,
      "This finding is about you, so someone else must decide it",
    ),
  });
  renderAt("/audit");
  fireEvent.change(await screen.findByLabelText("Why"), {
    target: { value: "Fine" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(
    await screen.findByText(
      "This finding is about you, so someone else must decide it",
    ),
  ).toBeDefined();
});

it("starts an audit, and shows when none has found anything", async () => {
  const fetchMock = asManager([], { "POST /api/audits": waiting });
  renderAt("/audit");
  expect(await screen.findByText(/No audit yet/)).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Start an audit" }));
  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(
        ([path, init]) => path === "/api/audits" && init?.method === "POST",
      ),
    ).toBe(true);
  });
});

it("shows a finished audit's summary and a failed one's reason", async () => {
  asManager([
    {
      ...waiting,
      status: "failed",
      waiting_on: null,
      findings: [],
      steps: [],
      summary: "0 patterns for review",
      failure: "The Auditor isn't running",
    },
  ]);
  renderAt("/audit");
  expect(await screen.findByText("0 patterns for review")).toBeDefined();
  expect(screen.getByText("The Auditor isn't running")).toBeDefined();
  expect(screen.getByText(/found no pattern/)).toBeDefined();
});

it("keeps asking only while an audit works, and reads evidence as words", () => {
  expect(isWorking([waiting])).toBe(false);
  expect(isWorking([{ ...waiting, status: "working" }])).toBe(true);
  expect(evidenceRows(finding.evidence)).toEqual([
    ["raises", "2"],
    ["link kinds", "shared phone"],
  ]);
});

it("says when a finding is about the manager", async () => {
  asManager([
    {
      ...waiting,
      waiting_on: null,
      findings: [{ ...finding, subject: "Elena Marsh" }],
    },
  ]);
  renderAt("/audit");
  expect(
    await screen.findByText(
      "This finding is about you, so someone else must decide it.",
    ),
  ).toBeDefined();
});
