import { vi } from "vitest";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Decision, Job, VerificationItem } from "@/api";
import { formatMoney, formatWhen } from "@/lib/format";
import { deferred } from "@/test/deferred";
import { makeJob, makeVerification } from "@/test/fixtures";
import { API } from "@/test/handlers";
import { makePhoto, serveJob } from "@/test/job";
import { find } from "@/test/requests";
import { setCleanerId } from "@/lib/cleaner-session";
import { renderRoute } from "@/test/render";
import { server } from "@/test/server";

// Resizing needs createImageBitmap and a canvas, which jsdom lacks (Playwright covers it).
vi.mock("../resize", () => ({ resizeImage: async () => new Blob(["x"], { type: "image/jpeg" }) }));

// The job page lives inside the cleaner list layout, which needs a signed-in cleaner.
beforeEach(() => setCleanerId("c1"));

const SUBMIT = { name: "Submit for verification" };
const RETRY_VERIFY = { name: "Retry verification" };
const RETRY_PAYMENT = { name: "Retry payment" };
const HINT = "Add at least one before and one after photo.";

/** Opens /cleaner/j1 and waits for the job's address heading. */
async function open(job: Job, photos = [makePhoto(1, "before"), makePhoto(2, "after")]) {
  const state = serveJob(job, photos);
  renderRoute("/cleaner/j1");
  await screen.findByRole("heading", { name: job.address });
  return state;
}

describe("CleanerJob", () => {
  describe("loading", () => {
    it("shows the skeleton while loading, then the job", async () => {
      const gate = deferred();
      server.use(
        http.get(`${API}/jobs/:id`, async () => {
          await gate.promise;
          return HttpResponse.json(makeJob());
        }),
      );
      renderRoute("/cleaner/j1");
      try {
        expect(screen.getByRole("status", { name: "Loading job" })).toBeInTheDocument();
      } finally {
        gate.release();
      }
      expect(await screen.findByRole("heading", { name: "1 Main St" })).toBeInTheDocument();
      expect(screen.queryByRole("status", { name: "Loading job" })).not.toBeInTheDocument();
    });

    it("shows a full-page error when the first getJob fails", async () => {
      server.use(http.get(`${API}/jobs/:id`, () => HttpResponse.json({ detail: "no such job" }, { status: 404 })));
      renderRoute("/cleaner/j1");
      expect(await screen.findByRole("alert")).toHaveTextContent("no such job");
      expect(screen.queryByRole("status", { name: "Loading job" })).not.toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "1 Main St" })).not.toBeInTheDocument();
    });

    it("falls back to scheduled_at when service_date is null", async () => {
      await open(makeJob({ service_date: null, scheduled_at: "2026-11-20T09:00:00Z" }));
      expect(screen.getByText(formatWhen("2026-11-20T09:00:00Z"))).toBeInTheDocument();
    });
  });

  describe("submit and retry", () => {
    it("disables Submit and shows the hint when there are no photos", async () => {
      await open(makeJob(), []);
      expect(screen.getByRole("button", SUBMIT)).toBeDisabled();
      expect(screen.getByText(HINT)).toBeInTheDocument();
    });

    it("needs both a before and an after photo", async () => {
      await open(makeJob(), [makePhoto(1, "before")]);
      expect(screen.getByRole("button", SUBMIT)).toBeDisabled();
      expect(screen.getByText(HINT)).toBeInTheDocument();
    });

    it("enables Submit and drops the hint with one before and one after", async () => {
      await open(makeJob());
      expect(screen.getByRole("button", SUBMIT)).toBeEnabled();
      expect(screen.queryByText(HINT)).not.toBeInTheDocument();
    });

    it("lets a REJECTED job submit again", async () => {
      await open(makeJob({ status: "REJECTED" }));
      expect(screen.getByRole("button", SUBMIT)).toBeEnabled();
    });

    it("shows 'Checking the photos…' and disables the button while submitJob is pending", async () => {
      await open(makeJob());
      const gate = deferred();
      server.use(
        http.post(`${API}/jobs/:id/submit`, async () => {
          await gate.promise;
          return HttpResponse.json(makeJob({ status: "VERIFIED" }));
        }),
      );
      try {
        await userEvent.setup().click(screen.getByRole("button", SUBMIT));
        const busy = await screen.findByRole("button", { name: "Checking the photos…" });
        expect(busy).toBeDisabled();
      } finally {
        gate.release();
      }
      await waitFor(() => expect(screen.queryByRole("button", SUBMIT)).not.toBeInTheDocument());
    });

    it("shows the returned job's status badge after a successful submit", async () => {
      await open(makeJob());
      server.use(http.post(`${API}/jobs/:id/submit`, () => HttpResponse.json(makeJob({ status: "VERIFIED" }))));
      await userEvent.setup().click(screen.getByRole("button", SUBMIT));
      expect(await screen.findByText("Verified", { selector: "span" })).toBeInTheDocument();
      expect(find("POST", "/api/jobs/j1/submit")).toHaveLength(1);
    });

    it("keeps the error after the refresh and offers 'Retry verification' when submit fails into SUBMITTED", async () => {
      const state = await open(makeJob());
      server.use(
        http.post(`${API}/jobs/:id/submit`, () => {
          state.job = makeJob({ status: "SUBMITTED" }); // the vision call failed after the job moved on
          return HttpResponse.json({ detail: "Vision service is down" }, { status: 502 });
        }),
      );
      await userEvent.setup().click(screen.getByRole("button", SUBMIT));
      expect(await screen.findByRole("button", RETRY_VERIFY)).toBeEnabled();
      expect(screen.getByRole("alert")).toHaveTextContent("Vision service is down");
      expect(screen.queryByRole("button", SUBMIT)).not.toBeInTheDocument();
    });

    it("calls POST /verify from 'Retry verification'", async () => {
      await open(makeJob({ status: "SUBMITTED" }));
      await userEvent.setup().click(screen.getByRole("button", RETRY_VERIFY));
      await waitFor(() => expect(find("POST", "/api/jobs/j1/verify")).toHaveLength(1));
      expect(find("POST", "/api/jobs/j1/submit")).toHaveLength(0);
    });

    it.each(["VERIFIED", "PENDING_APPROVAL", "RELEASED", "CAPTURED", "PAID_OUT"])(
      "shows neither Submit nor Retry verification on %s",
      async (status) => {
        await open(makeJob({ status }));
        expect(screen.queryByRole("button", SUBMIT)).not.toBeInTheDocument();
        expect(screen.queryByRole("button", RETRY_VERIFY)).not.toBeInTheDocument();
      },
    );
  });

  describe("verification panel", () => {
    const item = (overrides: Partial<VerificationItem>): VerificationItem => ({
      item: "Wipe the counters",
      visible: true,
      pass: true,
      confidence: 0.9,
      note: "Counters look clean",
      ...overrides,
    });

    it.each([
      [true, "Checks passed"],
      [false, "Some items need attention"],
    ])("titles the panel by overall_pass=%s", async (overall_pass, title) => {
      await open(makeJob({ status: "VERIFIED", verification: makeVerification({ results: { overall_pass, items: [] } }) }));
      expect(screen.getByRole("region", { name: title })).toBeInTheDocument();
    });

    it("reads Passed, Failed or Not visible for each item, and swaps the note for a not-visible item", async () => {
      await open(
        makeJob({
          status: "VERIFIED",
          verification: makeVerification({
            results: {
              overall_pass: false,
              items: [
                item({ item: "Wipe the counters", pass: true, note: "Counters look clean" }),
                item({ item: "Mop the floor", pass: false, note: "Streaks left on the floor" }),
                item({ item: "Empty the bins", visible: false, pass: false, note: "should be hidden" }),
              ],
            },
          }),
        }),
      );
      const panel = screen.getByRole("region", { name: "Some items need attention" });
      const row = (name: string) => within(panel).getByText(name, { exact: false }).closest("li")!;
      expect(row("Wipe the counters")).toHaveTextContent("Passed");
      expect(row("Wipe the counters")).toHaveTextContent("Counters look clean");
      expect(row("Mop the floor")).toHaveTextContent("Failed");
      expect(row("Mop the floor")).toHaveTextContent("Streaks left on the floor");
      expect(row("Empty the bins")).toHaveTextContent("Not visible");
      expect(row("Empty the bins")).toHaveTextContent("Not visible in the after photos");
      expect(within(panel).queryByText("should be hidden")).not.toBeInTheDocument();
    });

    it("shows 'Score –' for a null score and names the model", async () => {
      await open(makeJob({ status: "VERIFIED", verification: makeVerification({ score: null, model: "vision-9" }) }));
      expect(screen.getByText("Score –")).toBeInTheDocument();
      expect(screen.getByText("Checked by vision-9")).toBeInTheDocument();
    });

    it("shows the score when there is one", async () => {
      await open(makeJob({ status: "VERIFIED", verification: makeVerification({ score: "0.92" }) }));
      expect(screen.getByText("Score 0.92")).toBeInTheDocument();
    });
  });

  describe("decision panel", () => {
    const reasons = ["All items passed"];
    const decision = (outcome: Decision["outcome"]): Decision => ({ outcome, reasons });

    it.each([
      ["RELEASED", "auto_release", "Released for payment"],
      ["CAPTURED", "auto_release", "Released for payment"],
      ["PAID_OUT", "auto_release", "Released for payment"],
      ["PENDING_APPROVAL", "needs_approval", "Waiting for a manager to approve"],
      ["REJECTED", "reject", "Re-clean needed"],
    ] as const)("shows the %s / %s decision", async (status, outcome, title) => {
      await open(makeJob({ status, decision: decision(outcome) }));
      // The timeline repeats some of these titles, so look inside the panel that holds the reasons.
      const panel = screen.getByText("All items passed").closest("[role=status]") as HTMLElement;
      expect(within(panel).getByText(title)).toBeInTheDocument();
    });

    it.each([
      ["PENDING_APPROVAL", "auto_release"],
      ["AUTHORIZED", "reject"],
      ["VERIFIED", "needs_approval"],
      ["RELEASED", "needs_approval"],
      ["REJECTED", "auto_release"],
    ] as const)("shows nothing for a stale %s / %s decision", async (status, outcome) => {
      await open(makeJob({ status, decision: decision(outcome) }));
      expect(screen.queryByText("All items passed")).not.toBeInTheDocument();
    });

    it("shows nothing when there is no decision", async () => {
      await open(makeJob({ status: "RELEASED", decision: null }));
      expect(screen.queryByText("Released for payment", { selector: "p" })).not.toBeInTheDocument();
    });
  });

  describe("payment panel", () => {
    it.each([
      ["RELEASED", null, "Payment not collected yet", true],
      ["CAPTURED", { amount: "8.00", status: "PENDING" }, "Payout on the way", true],
      ["CAPTURED", { amount: "8.00", status: "FAILED" }, "Payout failed", false],
      ["PAID_OUT", { amount: "18.00", status: "SUCCESS" }, `${formatMoney("18.00")} paid to your PayPal`, false],
      ["PAID_OUT", null, `${formatMoney("10.00")} paid to your PayPal`, false],
    ] as const)("%s with payout %j shows %s (retry: %s)", async (status, payout, title, retry) => {
      await open(makeJob({ status, payout: payout && { ...payout } }));
      const panel = screen.getByRole("region", { name: "Payment" });
      expect(within(panel).getByText(title)).toBeInTheDocument();
      expect(within(panel).queryByRole("button", RETRY_PAYMENT) !== null).toBe(retry);
    });

    it("shows no payment panel for AUTHORIZED", async () => {
      await open(makeJob({ status: "AUTHORIZED", payout: null }));
      expect(screen.queryByRole("region", { name: "Payment" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", RETRY_PAYMENT)).not.toBeInTheDocument();
    });

    it("retries through POST /settle, shows 'Retrying…', then the new status", async () => {
      await open(makeJob({ status: "RELEASED" }));
      const gate = deferred();
      server.use(
        http.post(`${API}/jobs/:id/settle`, async () => {
          await gate.promise;
          return HttpResponse.json(makeJob({ status: "PAID_OUT", payout: { amount: "8.00", status: "SUCCESS" } }));
        }),
      );
      try {
        await userEvent.setup().click(screen.getByRole("button", RETRY_PAYMENT));
        expect(await screen.findByRole("button", { name: "Retrying…" })).toBeDisabled();
      } finally {
        gate.release();
      }
      expect(await screen.findByText(`${formatMoney("8.00")} paid to your PayPal`)).toBeInTheDocument();
      expect(screen.getByText("Paid out", { selector: "span" })).toBeInTheDocument();
      expect(screen.queryByRole("button", RETRY_PAYMENT)).not.toBeInTheDocument();
      expect(find("POST", "/api/jobs/j1/settle")).toHaveLength(1);
    });
  });
});
