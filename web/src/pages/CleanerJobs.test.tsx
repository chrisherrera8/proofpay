import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { getCleanerId, setCleanerId } from "@/lib/cleaner-session";
import { formatDay } from "@/lib/format";
import { deferred } from "@/test/deferred";
import { API } from "@/test/handlers";
import { makeCleaner, makeJob } from "@/test/fixtures";
import { requests, find } from "@/test/requests";
import { renderRoute } from "@/test/render";
import { server } from "@/test/server";
import type { Job } from "@/api";

/** Serve one list of jobs, whatever the query. */
function serveJobs(jobs: Job[]) {
  server.use(http.get(`${API}/jobs`, () => HttpResponse.json(jobs)));
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
      // A plain redirect carries no expired flag: the router reports state as null.
      expect(screen.getByTestId("state")).toHaveTextContent(/^null$/);
    });

    it("clears the id and redirects with state.expired when getCleaner is 404", async () => {
      server.use(http.get(`${API}/cleaners/:id`, () => HttpResponse.json({ detail: "gone" }, { status: 404 })));
      renderRoute("/cleaner");
      await waitFor(() => expect(screen.getByTestId("pathname")).toHaveTextContent("/cleaner/signup"));
      expect(JSON.parse(screen.getByTestId("state").textContent!)).toMatchObject({ expired: true });
      expect(getCleanerId()).toBeNull();
    });

    it("shows the error and keeps the id when getCleaner is 500", async () => {
      server.use(http.get(`${API}/cleaners/:id`, () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
      renderRoute("/cleaner");
      expect(await screen.findByRole("alert")).toHaveTextContent("boom");
      expect(screen.getByTestId("pathname")).toHaveTextContent(/^\/cleaner$/);
      expect(getCleanerId()).toBe("c1");
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
    it("shows the loading status until the list arrives", async () => {
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
      await screen.findByText("No jobs yet");
      expect(screen.queryByRole("status", { name: "Loading jobs" })).not.toBeInTheDocument();
    });

    it("shows the empty state when there are no jobs", async () => {
      renderRoute("/cleaner");
      expect(await screen.findByText("No jobs yet")).toBeInTheDocument();
      expect(screen.queryByRole("group", { name: "Filter by status" })).not.toBeInTheDocument();
    });

    it("shows the error and drops the skeleton when listJobs fails", async () => {
      server.use(http.get(`${API}/jobs`, () => HttpResponse.json({ detail: "jobs down" }, { status: 500 })));
      renderRoute("/cleaner");
      expect(await screen.findByRole("alert")).toHaveTextContent("jobs down");
      expect(screen.queryByRole("status", { name: "Loading jobs" })).not.toBeInTheDocument();
    });

    it("lists REJECTED jobs before AUTHORIZED ones", async () => {
      serveJobs([
        makeJob({ id: "j-auth", address: "Auth St" }),
        makeJob({ id: "j-rej", status: "REJECTED", address: "Rejected Rd" }),
      ]);
      renderRoute("/cleaner");
      await screen.findByText("Rejected Rd");
      const rows = screen.getAllByRole("link", { name: /Rejected Rd|Auth St/ });
      expect(rows).toHaveLength(2);
      expect(rows[0]).toHaveTextContent("Rejected Rd");
      expect(rows[1]).toHaveTextContent("Auth St");
    });

    it("requests all jobs with cleaner_id=c1, no status and limit=200", async () => {
      renderRoute("/cleaner");
      await screen.findByText("No jobs yet");
      const calls = find("GET", "/api/jobs");
      // StrictMode runs the effect twice in tests, so check every call rather than counting them.
      expect(calls.length).toBeGreaterThan(0);
      for (const r of calls) {
        expect(r.url.searchParams.get("cleaner_id")).toBe("c1");
        expect(r.url.searchParams.has("status")).toBe(false);
        expect(r.url.searchParams.get("limit")).toBe("200");
      }
    });

    it("names the tier, falls back to the raw type, and shows the date or a placeholder", async () => {
      serveJobs([
        makeJob({ id: "j-deep", service_type: "deep", service_date: "2026-11-20", address: "A St" }),
        makeJob({ id: "j-odd", service_type: "mystery", service_date: null, address: "B St" }),
      ]);
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
      serveJobs([first, second]);
      renderRoute("/cleaner");
      expect(await screen.findByRole("link", { name: /First St/ })).toHaveAttribute("href", `/cleaner/${first.id}`);
      expect(screen.getByRole("link", { name: /Second St/ })).toHaveAttribute("href", `/cleaner/${second.id}`);
    });
  });

  describe("sections and filter", () => {
    const mixed = () => [
      makeJob({ id: "a1", status: "AUTHORIZED", address: "Auth St" }),
      makeJob({ id: "r1", status: "REJECTED", address: "Rejected Rd" }),
      makeJob({ id: "s1", status: "SUBMITTED", address: "Submitted Ave" }),
      makeJob({ id: "p1", status: "PAID_OUT", address: "Paid Ln" }),
      makeJob({ id: "p2", status: "PAID_OUT", address: "Paid Ct" }),
    ];
    const chips = () => within(screen.getByRole("group", { name: "Filter by status" }));

    it("renders sections in order with headings and counts, hiding empty ones", async () => {
      serveJobs(mixed());
      renderRoute("/cleaner");
      await screen.findByText("Rejected Rd");
      const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
      expect(headings).toEqual(["Needs your attention 2", "In review 1", "Completed 2"]);
      expect(screen.queryByRole("heading", { name: /^Payment/ })).not.toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: /^Upcoming/ })).not.toBeInTheDocument();
    });

    it("links every row to /cleaner/:id, including PAID_OUT", async () => {
      serveJobs(mixed());
      renderRoute("/cleaner");
      expect(await screen.findByRole("link", { name: /Paid Ln/ })).toHaveAttribute("href", "/cleaner/p1");
      expect(screen.getByRole("link", { name: /Submitted Ave/ })).toHaveAttribute("href", "/cleaner/s1");
    });

    it("shows chips only for present statuses, with counts, All pressed by default", async () => {
      serveJobs(mixed());
      renderRoute("/cleaner");
      await screen.findByText("Rejected Rd");
      expect(chips().getAllByRole("button").map((b) => b.textContent?.replace(/\s+/g, " ").trim())).toEqual([
        "All 5",
        "Re-clean needed 1",
        "Payment held 1",
        "Photos submitted 1",
        "Paid out 2",
      ]);
      expect(chips().getByRole("button", { name: /^All/ })).toHaveAttribute("aria-pressed", "true");
    });

    it("narrows the rows and sets ?status= when a chip is clicked, and All restores", async () => {
      const user = userEvent.setup();
      serveJobs(mixed());
      renderRoute("/cleaner");
      await screen.findByText("Rejected Rd");

      await user.click(chips().getByRole("button", { name: /Paid out/ }));
      expect(screen.getByTestId("search")).toHaveTextContent("?status=PAID_OUT");
      expect(chips().getByRole("button", { name: /Paid out/ })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getAllByRole("link", { name: /Paid/ })).toHaveLength(2);
      expect(screen.queryByText("Rejected Rd")).not.toBeInTheDocument();
      expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(["Completed 2"]);

      await user.click(chips().getByRole("button", { name: /^All/ }));
      expect(screen.getByTestId("search")).toHaveTextContent(/^$/);
      expect(screen.getByText("Rejected Rd")).toBeInTheDocument();
      expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(3);
    });

    it("pre-selects the chip from ?status= in the initial URL", async () => {
      serveJobs(mixed());
      renderRoute("/cleaner?status=REJECTED");
      await screen.findByText("Rejected Rd");
      expect(chips().getByRole("button", { name: /Re-clean needed/ })).toHaveAttribute("aria-pressed", "true");
      expect(screen.queryByText("Auth St")).not.toBeInTheDocument();
    });

    it("falls back to All for an unknown or absent-status ?status=", async () => {
      serveJobs(mixed());
      renderRoute("/cleaner?status=NOPE");
      await screen.findByText("Rejected Rd");
      expect(chips().getByRole("button", { name: /^All/ })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByText("Paid Ln")).toBeInTheDocument();
    });
  });

  describe("switching cleaner", () => {
    it("clears the id and lands on /cleaner/signup", async () => {
      const user = userEvent.setup();
      renderRoute("/cleaner");
      await user.click(await screen.findByRole("link", { name: "Switch cleaner" }));
      expect(getCleanerId()).toBeNull();
      await waitFor(() => expect(screen.getByTestId("pathname")).toHaveTextContent("/cleaner/signup"));
      expect(screen.getByTestId("state")).toHaveTextContent(/^null$/);
    });
  });
});
