import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setCleanerId } from "@/lib/cleaner-session";
import { formatDay } from "@/lib/format";
import { deferred } from "@/test/deferred";
import { API } from "@/test/handlers";
import { makeCleaner, makeJob } from "@/test/fixtures";
import { requests, find } from "@/test/requests";
import { renderRoute } from "@/test/render";
import { server } from "@/test/server";
import type { Job } from "@/api";

/** Serve jobs by status, so the AUTHORIZED and REJECTED calls can return different lists. */
function serveJobs(byStatus: { AUTHORIZED?: Job[]; REJECTED?: Job[] }) {
  server.use(
    http.get(`${API}/jobs`, ({ request }) => {
      const status = new URL(request.url).searchParams.get("status") as "AUTHORIZED" | "REJECTED";
      return HttpResponse.json(byStatus[status] ?? []);
    }),
  );
}

describe("CleanerJobs", () => {
  beforeEach(() => setCleanerId("c1"));

  describe("session", () => {
    it("redirects to signup without calling the API when no id is stored", async () => {
      localStorage.clear();
      renderRoute("/cleaner");
      await waitFor(() => expect(screen.getByTestId("pathname")).toHaveTextContent("/cleaner/signup"));
      expect(find("GET", "/api/cleaners/c1")).toHaveLength(0);
      expect(find("GET", "/api/jobs")).toHaveLength(0);
    });

    it("clears the id and redirects with state.expired when getCleaner is 404", async () => {
      server.use(http.get(`${API}/cleaners/:id`, () => HttpResponse.json({ detail: "gone" }, { status: 404 })));
      renderRoute("/cleaner");
      await waitFor(() => expect(screen.getByTestId("pathname")).toHaveTextContent("/cleaner/signup"));
      expect(screen.getByTestId("state")).toHaveTextContent('{"expired":true}');
      expect(localStorage.getItem("proofpay.cleanerId")).toBeNull();
      expect(await screen.findByText(/that cleaner account has expired/i)).toBeInTheDocument();
    });

    it("shows the error and keeps the id when getCleaner is 500", async () => {
      server.use(http.get(`${API}/cleaners/:id`, () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
      renderRoute("/cleaner");
      expect(await screen.findByRole("alert")).toHaveTextContent("boom");
      expect(screen.getByTestId("pathname")).toHaveTextContent(/^\/cleaner$/);
      expect(localStorage.getItem("proofpay.cleanerId")).toBe("c1");
    });

    it("greets the cleaner by name once loaded, and says 'Your jobs' before", async () => {
      const gate = deferred();
      server.use(
        http.get(`${API}/cleaners/:id`, async () => {
          await gate.promise;
          return HttpResponse.json(makeCleaner({ name: "Ana" }));
        }),
      );
      try {
        renderRoute("/cleaner");
        expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Your jobs");
      } finally {
        gate.release();
      }
      expect(await screen.findByRole("heading", { level: 1, name: "Ana's jobs" })).toBeInTheDocument();
    });
  });

  describe("job list", () => {
    it("shows the loading status until the lists arrive", async () => {
      const gate = deferred();
      server.use(
        http.get(`${API}/jobs`, async () => {
          await gate.promise;
          return HttpResponse.json([]);
        }),
      );
      try {
        renderRoute("/cleaner");
        expect(screen.getByRole("status", { name: "Loading jobs" })).toBeInTheDocument();
      } finally {
        gate.release();
      }
      await screen.findByText("No jobs waiting");
      expect(screen.queryByRole("status", { name: "Loading jobs" })).not.toBeInTheDocument();
    });

    it("shows the empty state when both lists are empty", async () => {
      renderRoute("/cleaner");
      expect(await screen.findByText("No jobs waiting")).toBeInTheDocument();
      expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    });

    it("shows the error and drops the skeleton when listJobs fails", async () => {
      server.use(http.get(`${API}/jobs`, () => HttpResponse.json({ detail: "jobs down" }, { status: 500 })));
      renderRoute("/cleaner");
      expect(await screen.findByRole("alert")).toHaveTextContent("jobs down");
      expect(screen.queryByRole("status", { name: "Loading jobs" })).not.toBeInTheDocument();
    });

    it("lists REJECTED jobs before AUTHORIZED ones", async () => {
      serveJobs({
        AUTHORIZED: [makeJob({ id: "j-auth", address: "Auth St" })],
        REJECTED: [makeJob({ id: "j-rej", status: "REJECTED", address: "Rejected Rd" })],
      });
      renderRoute("/cleaner");
      await screen.findByText("Rejected Rd");
      const rows = screen.getAllByRole("listitem");
      expect(rows).toHaveLength(2);
      expect(rows[0]).toHaveTextContent("Rejected Rd");
      expect(rows[1]).toHaveTextContent("Auth St");
    });

    it("sends cleaner_id=c1 on both job requests", async () => {
      renderRoute("/cleaner");
      await screen.findByText("No jobs waiting");
      const calls = find("GET", "/api/jobs");
      expect(calls.map((r) => r.url.searchParams.get("status"))).toEqual(
        expect.arrayContaining(["AUTHORIZED", "REJECTED"]),
      );
      for (const r of calls) expect(r.url.searchParams.get("cleaner_id")).toBe("c1");
    });

    it("names the tier, falls back to the raw type, and shows the date or a placeholder", async () => {
      serveJobs({
        AUTHORIZED: [
          makeJob({ id: "j-deep", service_type: "deep", service_date: "2026-11-20", address: "A St" }),
          makeJob({ id: "j-odd", service_type: "mystery", service_date: null, address: "B St" }),
        ],
      });
      renderRoute("/cleaner");
      const deep = await screen.findByRole("link", { name: /A St/ });
      const odd = screen.getByRole("link", { name: /B St/ });
      expect(within(deep).getByText("Deep Clean")).toBeInTheDocument();
      expect(within(deep).getByText(formatDay("2026-11-20"))).toBeInTheDocument();
      expect(within(odd).getByText("mystery")).toBeInTheDocument();
      expect(within(odd).getByText("Date to be confirmed")).toBeInTheDocument();
    });

    it("links each row to /cleaner/:id", async () => {
      const first = makeJob({ id: "7", address: "First St" });
      const second = makeJob({ id: "8", address: "Second St" });
      serveJobs({ AUTHORIZED: [first, second] });
      renderRoute("/cleaner");
      expect(await screen.findByRole("link", { name: /First St/ })).toHaveAttribute("href", `/cleaner/${first.id}`);
      expect(screen.getByRole("link", { name: /Second St/ })).toHaveAttribute("href", `/cleaner/${second.id}`);
    });
  });

  describe("switching cleaner", () => {
    it("clears the id and lands on /cleaner/signup", async () => {
      const user = userEvent.setup();
      renderRoute("/cleaner");
      await user.click(await screen.findByRole("link", { name: "Switch cleaner" }));
      expect(localStorage.getItem("proofpay.cleanerId")).toBeNull();
      await waitFor(() => expect(screen.getByTestId("pathname")).toHaveTextContent("/cleaner/signup"));
    });
  });
});
