import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Job } from "@/api";
import { setCleanerId } from "@/lib/cleaner-session";
import { makeJob } from "@/test/fixtures";
import { API } from "@/test/handlers";
import { serveJob } from "@/test/job";
import { renderRoute } from "@/test/render";
import { find } from "@/test/requests";
import { server } from "@/test/server";

const DELETE = { name: "Delete job" };

beforeEach(() => setCleanerId("c1"));
afterEach(() => vi.restoreAllMocks());

async function open(job: Job) {
  serveJob(job);
  server.use(http.get(`${API}/jobs`, () => HttpResponse.json([job])));
  renderRoute(`/cleaner/${job.id}`);
  await screen.findByRole("heading", { level: 1, name: job.address });
}

describe("CleanerJob delete", () => {
  it.each(["BOOKED", "PAID_OUT"] as const)("offers Delete for a %s job", async (status) => {
    await open(makeJob({ id: "j1", status }));
    expect(screen.getByRole("button", DELETE)).toBeInTheDocument();
  });

  it.each(["AUTHORIZED", "SUBMITTED", "PENDING_APPROVAL", "RELEASED", "CAPTURED", "REJECTED"] as const)(
    "hides Delete for a %s job (money is held)",
    async (status) => {
      await open(makeJob({ id: "j1", status }));
      expect(screen.queryByRole("button", DELETE)).not.toBeInTheDocument();
    },
  );

  it("sends nothing when the confirm prompt is cancelled", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    await open(makeJob({ id: "j1", status: "BOOKED" }));
    await userEvent.click(screen.getByRole("button", DELETE));
    expect(window.confirm).toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1, name: "1 Main St" })).toBeInTheDocument();
    expect(find("DELETE", "/api/jobs/j1")).toHaveLength(0);
  });

  it("deletes the job, drops it from the list and returns to the list", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    server.use(http.delete(`${API}/jobs/:id`, () => {
      return new HttpResponse(null, { status: 204 });
    }));
    await open(makeJob({ id: "j1", status: "BOOKED" }));
    await userEvent.click(screen.getByRole("button", DELETE));
    await waitFor(() => expect(find("DELETE", "/api/jobs/j1")).toHaveLength(1));
    await waitFor(() => expect(screen.getByTestId("pathname")).toHaveTextContent(/^\/cleaner$/));
    expect(screen.queryByRole("link", { name: /1 Main St/ })).not.toBeInTheDocument();
    expect(await screen.findByText("No jobs yet")).toBeInTheDocument();
  });

  it("shows the server's error and keeps the job when delete fails", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    server.use(http.delete(`${API}/jobs/:id`, () =>
      HttpResponse.json({ detail: "Job is AUTHORIZED; cannot delete" }, { status: 409 })));
    await open(makeJob({ id: "j1", status: "BOOKED" }));
    await userEvent.click(screen.getByRole("button", DELETE));
    expect(await screen.findByRole("alert")).toHaveTextContent("cannot delete");
    expect(screen.getByRole("heading", { level: 1, name: "1 Main St" })).toBeInTheDocument();
    expect(screen.getByRole("button", DELETE)).toBeEnabled();
  });
});
