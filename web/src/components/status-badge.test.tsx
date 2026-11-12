import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { STATUS, StatusBadge } from "./status-badge";

describe("StatusBadge", () => {
  it.each(Object.entries(STATUS))("%s shows its label", (status, { label }) => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("renders an unknown status as lower-case words", () => {
    render(<StatusBadge status="ON_HOLD" />);
    expect(screen.getByText("on hold")).toBeInTheDocument();
  });
});
