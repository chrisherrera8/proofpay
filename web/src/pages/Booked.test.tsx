import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { formatDay, formatMoney, formatWhen } from "@/lib/format";
import { deferred } from "@/test/deferred";
import { API } from "@/test/handlers";
import { makeJob } from "@/test/fixtures";
import { renderRoute } from "@/test/render";
import { server } from "@/test/server";
import type { Job } from "@/api";

function serve(job: Job) {
  server.use(http.get(`${API}/jobs/:id`, () => HttpResponse.json(job)));
}

describe("Booked", () => {
  it("shows the loading skeleton, then the booking", async () => {
    const gate = deferred();
    server.use(
      http.get(`${API}/jobs/:id`, async () => {
        await gate.promise;
        return HttpResponse.json(makeJob());
      }),
    );
    try {
      renderRoute("/booked/j1");
      expect(screen.getByRole("status", { name: "Loading your booking" })).toBeInTheDocument();
    } finally {
      gate.release();
    }
    expect(await screen.findByRole("heading", { name: "You're booked" })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading your booking" })).not.toBeInTheDocument();
  });

  it("shows the error alert when getJob is 404", async () => {
    server.use(http.get(`${API}/jobs/:id`, () => HttpResponse.json({ detail: "Job not found" }, { status: 404 })));
    renderRoute("/booked/nope");
    expect(await screen.findByRole("alert")).toHaveTextContent("Job not found");
    expect(screen.queryByRole("heading", { name: "You're booked" })).not.toBeInTheDocument();
  });

  it("shows the customer, tier, amount, details and checklist", async () => {
    serve(
      makeJob({
        service_type: "deep",
        amount: "20.00",
        checklist_items: [
          { id: 1, label: "Wipe the counters", required: true, position: 1 },
          { id: 2, label: "Mop the floor", required: true, position: 2 },
        ],
      }),
    );
    renderRoute("/booked/j1");
    await screen.findByRole("heading", { name: "You're booked" });
    expect(screen.getByText(/Thanks, Sam\./)).toBeInTheDocument();
    expect(screen.getByText("Deep Clean")).toBeInTheDocument();
    expect(screen.getByText(formatMoney("20.00"))).toBeInTheDocument();
    expect(screen.getByText(formatDay("2026-11-20"))).toBeInTheDocument();
    expect(screen.getByText("Ana")).toBeInTheDocument();
    expect(screen.getByText("1 Main St")).toBeInTheDocument();
    expect(screen.getByText("Wipe the counters")).toBeInTheDocument();
    expect(screen.getByText("Mop the floor")).toBeInTheDocument();
  });

  it("explains a deleted cleaner when cleaner_name is null", async () => {
    serve(makeJob({ cleaner_name: null, cleaner_id: null }));
    renderRoute("/booked/j1");
    expect(await screen.findByText("Your cleaner (their demo data has been deleted)")).toBeInTheDocument();
  });

  it("falls back to scheduled_at when service_date is null", async () => {
    serve(makeJob({ service_date: null }));
    renderRoute("/booked/j1");
    await screen.findByRole("heading", { name: "You're booked" });
    expect(screen.getByText(formatWhen("2026-11-20T09:00:00Z"))).toBeInTheDocument();
  });

  it("shows an unknown service_type as-is", async () => {
    serve(makeJob({ service_type: "mystery" as Job["service_type"] }));
    renderRoute("/booked/j1");
    await screen.findByRole("heading", { name: "You're booked" });
    expect(screen.getByText("mystery")).toBeInTheDocument();
  });
});
