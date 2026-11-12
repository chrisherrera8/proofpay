import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Field } from "./field";

describe("Field", () => {
  it("hint only: described by the hint", () => {
    render(<Field id="x" label="Name" hint="As on your card" />);
    const input = screen.getByLabelText("Name");
    expect(input).toHaveAttribute("aria-describedby", "x-hint");
    expect(input).toHaveAttribute("aria-invalid", "false");
    expect(screen.getByText("As on your card")).toHaveAttribute("id", "x-hint");
  });

  it("error only: described by the error and marked invalid", () => {
    render(<Field id="x" label="Name" error="Enter your name." />);
    const input = screen.getByLabelText("Name");
    expect(input).toHaveAttribute("aria-describedby", "x-err");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Enter your name.")).toHaveAttribute("id", "x-err");
  });

  it("neither: no aria-describedby", () => {
    render(<Field id="x" label="Name" />);
    expect(screen.getByLabelText("Name")).not.toHaveAttribute("aria-describedby");
  });

  it("both: hides the hint and only points at the error", () => {
    render(<Field id="x" label="Name" hint="As on your card" error="Enter your name." />);
    expect(screen.queryByText("As on your card")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveAttribute("aria-describedby", "x-err");
  });
});
