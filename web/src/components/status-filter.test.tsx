import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StatusFilter } from "./status-filter";

const counts = [
  { status: "REJECTED", count: 1 },
  { status: "AUTHORIZED", count: 2 },
];

describe("StatusFilter", () => {
  it("renders All with the total plus one chip per status, labelled from STATUS", () => {
    render(<StatusFilter counts={counts} value={null} onChange={() => {}} />);
    const group = screen.getByRole("group", { name: "Filter by status" });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All 3" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Re-clean needed 1" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Payment held 2" })).toBeInTheDocument();
  });

  it("marks the selected status pressed", () => {
    render(<StatusFilter counts={counts} value="REJECTED" onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "Re-clean needed 1" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "All 3" })).toHaveAttribute("aria-pressed", "false");
  });

  it("calls onChange with the status, and null for All", async () => {
    const onChange = vi.fn();
    render(<StatusFilter counts={counts} value="REJECTED" onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Payment held 2" }));
    expect(onChange).toHaveBeenLastCalledWith("AUTHORIZED");
    await userEvent.click(screen.getByRole("button", { name: "All 3" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});
