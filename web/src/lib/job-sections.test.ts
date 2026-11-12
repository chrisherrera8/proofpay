import { describe, expect, it } from "vitest";
import type { Job } from "../api";
import { displayStatus, groupJobs, statusCounts } from "./job-sections";

let n = 0;
const job = (status: string, service_date: string | null = "2026-11-10"): Job =>
  ({ id: `j${++n}`, status, service_date }) as Job;

describe("groupJobs", () => {
  it("orders sections by what the cleaner should do", () => {
    const jobs = ["BOOKED", "PAID_OUT", "CAPTURED", "SUBMITTED", "AUTHORIZED"].map((s) => job(s));
    expect(groupJobs(jobs).map((g) => g.section.id)).toEqual(["attention", "review", "payment", "completed", "upcoming"]);
  });

  it("drops empty sections", () => {
    expect(groupJobs([job("PAID_OUT")]).map((g) => g.section.id)).toEqual(["completed"]);
    expect(groupJobs([])).toEqual([]);
  });

  it("puts REJECTED before AUTHORIZED, then earliest service date first, nulls last", () => {
    const auth = job("AUTHORIZED", "2026-11-09");
    const authNull = job("AUTHORIZED", null);
    const authLate = job("AUTHORIZED", "2026-11-12");
    const rejected = job("REJECTED", "2026-11-20");
    const [group] = groupJobs([authNull, authLate, rejected, auth]);
    expect(group.jobs).toEqual([rejected, auth, authLate, authNull]);
  });

  it("filters to one status and keeps its section", () => {
    const rejected = job("REJECTED");
    const groups = groupJobs([rejected, job("AUTHORIZED"), job("PAID_OUT")], "REJECTED");
    expect(groups).toHaveLength(1);
    expect(groups[0].section.id).toBe("attention");
    expect(groups[0].jobs).toEqual([rejected]);
  });

  it("puts an unknown status in a trailing Other section", () => {
    const weird = job("FUTURE_STATUS");
    const groups = groupJobs([weird, job("BOOKED")]);
    expect(groups.map((g) => g.section.title)).toEqual(["Upcoming", "Other"]);
    expect(groups[1].jobs).toEqual([weird]);
  });
});

describe("statusCounts", () => {
  it("counts only present statuses, in section then status order", () => {
    const jobs = [job("PAID_OUT"), job("AUTHORIZED"), job("REJECTED"), job("AUTHORIZED"), job("BOOKED")];
    expect(statusCounts(jobs)).toEqual([
      { status: "REJECTED", count: 1 },
      { status: "AUTHORIZED", count: 2 },
      { status: "PAID_OUT", count: 1 },
      { status: "BOOKED", count: 1 },
    ]);
  });

  it("lists unknown statuses last", () => {
    expect(statusCounts([job("FUTURE_STATUS"), job("BOOKED")]).map((c) => c.status)).toEqual(["BOOKED", "FUTURE_STATUS"]);
  });

  it("returns nothing for no jobs", () => {
    expect(statusCounts([])).toEqual([]);
  });
});

describe("payout failed", () => {
  const failed = () => ({ ...job("CAPTURED"), payout: { amount: "10.00", status: "FAILED" } }) as Job;
  const pending = () => ({ ...job("CAPTURED"), payout: { amount: "10.00", status: "PENDING" } }) as Job;

  it("is its own status only for a CAPTURED job with a FAILED payout", () => {
    expect(displayStatus(failed())).toBe("PAYOUT_FAILED");
    expect(displayStatus(pending())).toBe("CAPTURED");
    expect(displayStatus(job("PAID_OUT"))).toBe("PAID_OUT");
  });

  it("gets its own chip and sits under Needs your attention", () => {
    const jobs = [pending(), failed()];
    expect(statusCounts(jobs).map((c) => c.status)).toEqual(["PAYOUT_FAILED", "CAPTURED"]);
    expect(groupJobs(jobs).map((g) => g.section.id)).toEqual(["attention", "payment"]);
    expect(groupJobs(jobs, "PAYOUT_FAILED").flatMap((g) => g.jobs)).toHaveLength(1);
  });
});
