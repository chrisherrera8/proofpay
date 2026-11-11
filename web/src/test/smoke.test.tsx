import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { API } from "./handlers";
import { makeJob } from "./fixtures";
import { requests } from "./requests";
import { renderRoute } from "./render";
import { server } from "./server";

describe("test setup", () => {
  it("renders a page, serves it data through MSW and finds it by role", async () => {
    server.use(http.get(`${API}/jobs/j1`, () => HttpResponse.json(makeJob({ id: "j1" }))));
    renderRoute("/booked/j1");
    expect(await screen.findByRole("heading", { name: "You're booked" })).toBeInTheDocument();
    expect(screen.getByTestId("pathname")).toHaveTextContent("/booked/j1");
    expect(requests.some((r) => r.method === "GET" && r.url.pathname === "/api/jobs/j1")).toBe(true);
  });
});
