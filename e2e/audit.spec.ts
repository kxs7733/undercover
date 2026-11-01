import { expect, test } from "@playwright/test";
import { HANDLERS } from "./handlers";

const NOT_MANAGER = /Only the claims operations manager can audit/;

const finding = {
  finding_id: 7,
  audit_id: "audit-1",
  check_name: "send_back_raises",
  subject: "Jonah Albright",
  subject_name: "Jonah Albright",
  fingerprint: "send_back_raises:Jonah Albright",
  score: 80,
  needs_decision: true,
  claim_ids: ["CLM-1001"],
  exposure: 2420,
  evidence: { raises: 2 },
  narrative: "Two send-backs ended in a higher payout, for review.",
  written_by_model: true,
  status: "open",
  answer_reason: null,
  answered_by: null,
  answered_at: null,
};
const waiting = {
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
  steps: [],
};

test.describe("as the manager", () => {
  test.use({ storageState: HANDLERS.elena.storage });

  test("an audit with no Auditor running says so", async ({ page }) => {
    await page.goto("/audit");
    await expect(page.getByRole("heading", { name: "Audit" })).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Agent versions" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Start an audit" }).click();
    await expect(
      page.getByRole("alert").filter({ hasText: "isn't running" }).first(),
    ).toBeVisible();
  });

  test("a finding waits for a reason, then the decision goes to the app", async ({
    page,
  }) => {
    await page.route("**/api/audits", (route) =>
      route.fulfill({ json: [waiting] }),
    );
    let sent: unknown;
    await page.route("**/api/audits/audit-1/findings/7/answer", (route) => {
      sent = route.request().postDataJSON();
      return route.fulfill({ status: 202, json: waiting });
    });
    await page.goto("/audit");
    const card = page.getByRole("article", {
      name: "Send-backs that raised a payout: Jonah Albright",
    });
    await expect(card.getByText(finding.narrative)).toBeVisible();
    const open = card.getByRole("button", { name: "Open a case" });
    await expect(open).toHaveAttribute("aria-disabled", "true");
    await card.getByLabel("Why").fill("Worth a look");
    await open.click();
    await expect
      .poll(() => sent)
      .toEqual({
        answer: "open_case",
        reason: "Worth a look",
      });
  });
});

test("anyone else is told they can't audit, with no link to the page", async ({
  page,
}) => {
  await page.goto("/audit");
  await expect(page.getByText(NOT_MANAGER)).toBeVisible();
  await expect(page.getByRole("link", { name: "Audit" })).toHaveCount(0);
});
