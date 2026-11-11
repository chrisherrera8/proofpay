import { afterEach, describe, expect, it, vi } from "vitest";
import { formatDay, formatMoney, todayLocal } from "./format";

// Node re-reads process.env.TZ on assignment, so each case can pick its own timezone.
const originalTZ = process.env.TZ;
const zones = ["Pacific/Auckland", "America/Los_Angeles"];

afterEach(() => {
  if (originalTZ === undefined) delete process.env.TZ;
  else process.env.TZ = originalTZ;
});

describe.each(zones)("in %s", (tz) => {
  it("formatDay shows the calendar day it was given", () => {
    process.env.TZ = tz;
    expect(formatDay("2026-11-10")).toMatch(/\b10\b/);
    expect(formatDay("2026-11-10")).toMatch(/Nov/);
  });

  it.each([[23, 30], [0, 30]])("todayLocal at %i:%i local returns the local date", (h, min) => {
    process.env.TZ = tz;
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 10, h, min));
    expect(todayLocal()).toBe("2026-11-10");
  });
});

describe("formatMoney", () => {
  it("formats strings and numbers", () => {
    expect(formatMoney("20.00")).toMatch(/20\.00/);
    expect(formatMoney(20)).toMatch(/20\.00/);
  });

  it("uses the given currency", () => {
    expect(formatMoney(5, "EUR")).toMatch(/€|EUR/);
    expect(formatMoney(5, "EUR")).toMatch(/5\.00/);
  });
});
