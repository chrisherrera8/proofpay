import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { JobTimeline } from "./job-timeline";

const TITLES = ["Booked", "Photos submitted", "Work verified", "Customer charged", "Cleaner paid"];

const steps = () => screen.getAllByRole("listitem");
const currentIndex = () => steps().findIndex((li) => li.getAttribute("aria-current") === "step");

describe("JobTimeline", () => {
  it.each([
    ["BOOKED", 0],
    ["AUTHORIZED", 1],
    ["REJECTED", 1],
    ["SUBMITTED", 2],
    ["VERIFIED", 2],
    ["PENDING_APPROVAL", 2],
    ["RELEASED", 3],
    ["CAPTURED", 4],
  ])("%s marks step %i as current", (status, step) => {
    render(<JobTimeline status={status} />);
    expect(steps()).toHaveLength(TITLES.length);
    expect(currentIndex()).toBe(step);
    expect(within(steps()[step]).getByText("(current step)", { exact: false })).toBeInTheDocument();
  });

  it("PAID_OUT: every step is done and none is current", () => {
    render(<JobTimeline status="PAID_OUT" />);
    expect(currentIndex()).toBe(-1);
    for (const li of steps()) expect(within(li).getByText("(done)", { exact: false })).toBeInTheDocument();
  });

  it("falls back to step 0 for an unknown status", () => {
    render(<JobTimeline status="ON_HOLD" />);
    expect(currentIndex()).toBe(0);
  });

  it("REJECTED explains the re-clean", () => {
    render(<JobTimeline status="REJECTED" />);
    expect(screen.getByText("Some items need a re-clean")).toBeInTheDocument();
  });

  it("PENDING_APPROVAL says it is waiting on a manager", () => {
    render(<JobTimeline status="PENDING_APPROVAL" />);
    expect(screen.getByText("Waiting for a manager to approve")).toBeInTheDocument();
  });
});
