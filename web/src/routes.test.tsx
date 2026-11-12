import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderRoute } from "@/test/render";

vi.mock("@paypal/react-paypal-js", async () => (await import("@/test/paypal-stub")).paypalModule);

const homeHeading = { name: /A spotless home/ };

describe("routing", () => {
  it("/ renders Home", async () => {
    renderRoute("/");
    expect(await screen.findByRole("heading", { level: 1, ...homeHeading })).toBeInTheDocument();
  });

  it("/book renders Book", async () => {
    renderRoute("/book");
    expect(await screen.findByRole("heading", { level: 1, name: "Book a clean" })).toBeInTheDocument();
  });

  it("/cleaner/signup renders the signup page, not a job", async () => {
    renderRoute("/cleaner/signup");
    expect(await screen.findByRole("heading", { level: 1, name: "Become a cleaner" })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading job" })).not.toBeInTheDocument();
  });

  it("/nope renders Home and keeps the URL", async () => {
    renderRoute("/nope");
    expect(await screen.findByRole("heading", { level: 1, ...homeHeading })).toBeInTheDocument();
    expect(screen.getByTestId("pathname")).toHaveTextContent("/nope");
  });
});
