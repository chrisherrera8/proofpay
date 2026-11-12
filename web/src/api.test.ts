import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import {
  ApiError,
  createJob,
  deletePhoto,
  getCleaner,
  getJob,
  listCleaners,
  listJobs,
  photoUrl,
  uploadPhoto,
} from "./api";
import { API } from "./test/handlers";
import { find, requests } from "./test/requests";
import { server } from "./test/server";

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (e) {
    return e as ApiError;
  }
  throw new Error("expected the call to reject");
}

describe("errors", () => {
  it("turns a network failure into a friendly ApiError with no status", async () => {
    server.use(http.get(`${API}/jobs/j1`, () => HttpResponse.error()));
    const err = await failure(getJob("j1"));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe("Can't reach the booking server. Check your connection and try again.");
    expect(err.status).toBeUndefined();
  });

  it("uses a string detail as the message and keeps the status", async () => {
    server.use(http.get(`${API}/jobs/j1`, () => HttpResponse.json({ detail: "Job not found" }, { status: 404 })));
    const err = await failure(getJob("j1"));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe("Job not found");
    expect(err.status).toBe(404);
  });

  it.each([
    {
      name: "joins list details by field and strips 'Value error, '",
      detail: [
        { loc: ["body", "name"], msg: "Value error, too long" },
        { loc: ["body", "email"], msg: "bad" },
      ],
      message: "name: too long; email: bad",
    },
    { name: "shows 'field: invalid' for items without loc or msg", detail: [{}], message: "field: invalid" },
  ])("422 $name", async ({ detail, message }) => {
    server.use(http.get(`${API}/jobs/j1`, () => HttpResponse.json({ detail }, { status: 422 })));
    const err = await failure(getJob("j1"));
    expect(err.message).toBe(message);
    expect(err.status).toBe(422);
  });

  it("falls back when detail is an object", async () => {
    server.use(http.get(`${API}/jobs/j1`, () => HttpResponse.json({ detail: { a: 1 } }, { status: 400 })));
    const err = await failure(getJob("j1"));
    expect(err.message).toBe("Something went wrong (400). Please try again.");
    expect(err.status).toBe(400);
  });

  it("falls back with the status when a 500 has no JSON body", async () => {
    server.use(http.get(`${API}/jobs/j1`, () => new HttpResponse(null, { status: 500 })));
    const err = await failure(getJob("j1"));
    expect(err.message).toBe("Something went wrong (500). Please try again.");
    expect(err.status).toBe(500);
  });

  it("throws an ApiError when an OK response isn't JSON", async () => {
    server.use(http.get(`${API}/jobs/j1`, () => HttpResponse.text("<html>oops</html>")));
    expect(await failure(getJob("j1"))).toBeInstanceOf(ApiError);
  });
});

describe("success and requests", () => {
  it("resolves a 204 from deletePhoto to undefined", async () => {
    await expect(deletePhoto("j1", 5)).resolves.toBeUndefined();
    expect(find("DELETE", "/api/jobs/j1/photos/5")).toHaveLength(1);
  });

  it("listJobs always sends the cleaner id", async () => {
    await listJobs("AUTHORIZED", "c1");
    const [req] = find("GET", "/api/jobs");
    expect(req.url.searchParams.get("status")).toBe("AUTHORIZED");
    expect(req.url.searchParams.get("cleaner_id")).toBe("c1");
  });

  it("listJobs encodes status and cleaner id", async () => {
    await listJobs("A&B", "x/y");
    const [req] = find("GET", "/api/jobs");
    expect(req.url.search).toBe("?status=A%26B&cleaner_id=x%2Fy");
  });

  it("getCleaner encodes the id", async () => {
    await getCleaner("a/b");
    expect(requests[0].url.pathname).toBe("/api/cleaners/a%2Fb");
  });

  it("listCleaners encodes the date", async () => {
    await listCleaners("2026-11-20 x");
    const [req] = find("GET", "/api/cleaners");
    expect(req.url.search).toBe("?date=2026-11-20%20x");
  });

  it("createJob POSTs a JSON body with a JSON content type", async () => {
    const body = {
      customer_name: "Sam",
      customer_email: "sam@example.com",
      address: "1 Main St",
      service_type: "basic",
      cleaner_id: "c1",
      service_date: "2026-11-20",
      amount: 10,
    };
    await createJob(body);
    const [req] = find("POST", "/api/jobs");
    expect(req.headers.get("content-type")).toBe("application/json");
    expect(req.body).toEqual(body);
  });

  it("uploadPhoto sends the raw blob with its own content type and ?kind=before", async () => {
    // jsdom's Blob isn't Node's, so MSW would only see "[object Blob]". Check what api.ts hands to fetch.
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ id: 1, kind: "before" }));
    const blob = new Blob(["pixels"], { type: "image/jpeg" });
    await uploadPhoto("j1", "before", blob);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/jobs/j1/photos?kind=before");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(blob);
    expect(init?.headers).toEqual({ "Content-Type": "image/jpeg" });
  });

  it("photoUrl builds the photo endpoint URL", () => {
    expect(photoUrl("j1", 7)).toBe("http://localhost:8000/api/jobs/j1/photos/7");
  });
});
