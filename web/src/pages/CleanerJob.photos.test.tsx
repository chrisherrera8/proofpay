import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { photoUrl, type Job, type Photo } from "@/api";
import { deferred } from "@/test/deferred";
import { makeJob } from "@/test/fixtures";
import { API } from "@/test/handlers";
import { makePhoto, serveJob } from "@/test/job";
import { find } from "@/test/requests";
import { setCleanerId } from "@/lib/cleaner-session";
import { renderRoute } from "@/test/render";
import { server } from "@/test/server";

// Resizing needs createImageBitmap and a canvas, which jsdom lacks (Playwright covers it).
vi.mock("../resize", () => ({ resizeImage: async () => new Blob(["x"], { type: "image/jpeg" }) }));

// The job page lives inside the cleaner list layout, which needs a signed-in cleaner.
beforeEach(() => setCleanerId("c1"));

const file = (name: string) => new File(["x"], name, { type: "image/jpeg" });
const files = (n: number) => Array.from({ length: n }, (_, i) => file(`p${i}.jpg`));
const before = () => screen.getByRole("region", { name: "Before photos" });
const after = () => screen.getByRole("region", { name: "After photos" });
const fileInput = (section: HTMLElement) => section.querySelector("input[type=file]") as HTMLInputElement;
const uploads = (kind: Photo["kind"]) =>
  find("POST", "/api/jobs/j1/photos").filter((r) => r.url.searchParams.get("kind") === kind);

/** Opens /cleaner/j1 with a photo store that the upload and delete handlers below keep in step. */
async function open(initial: Photo[] = [], job: Job = makeJob()) {
  const state = serveJob(job, [...initial]);
  let nextId = 100;
  server.use(
    http.post(`${API}/jobs/:id/photos`, ({ request }) => {
      const kind = new URL(request.url).searchParams.get("kind") as Photo["kind"];
      const photo = makePhoto(nextId++, kind);
      state.photos = [...state.photos, photo];
      return HttpResponse.json(photo);
    }),
    http.delete(`${API}/jobs/:id/photos/:photoId`, ({ params }) => {
      state.photos = state.photos.filter((p) => String(p.id) !== params.photoId);
      return new HttpResponse(null, { status: 204 });
    }),
  );
  renderRoute("/cleaner/j1");
  await screen.findByRole("heading", { name: job.address });
  return state;
}

describe("CleanerJob photos", () => {
  it("counts n/4 per kind and removes the add tile at 4", async () => {
    await open([makePhoto(1), makePhoto(2), makePhoto(3), makePhoto(4), makePhoto(5, "after")]);
    expect(within(before()).getByText("4/4")).toBeInTheDocument();
    expect(within(after()).getByText("1/4")).toBeInTheDocument();
    expect(within(before()).queryByRole("button", { name: /photo$/ })).not.toBeInTheDocument();
    expect(fileInput(before())).toBeNull();
    expect(within(after()).getByRole("button", { name: "Add photo" })).toBeInTheDocument();
  });

  it("uploads each chosen file as ?kind=before, then refreshes", async () => {
    await open();
    await userEvent.setup().upload(fileInput(before()), files(2));
    expect(await within(before()).findByRole("img", { name: "Before photo 2" })).toBeInTheDocument();
    expect(uploads("before")).toHaveLength(2);
    expect(uploads("after")).toHaveLength(0);
    expect(uploads("before")[0].headers.get("content-type")).toBe("image/jpeg");
    expect(within(before()).getByText("2/4")).toBeInTheDocument();
  });

  it("uploads only as many files as fit under the cap", async () => {
    // Files over the cap are dropped silently today; Phase 8 decides whether to say so.
    await open([makePhoto(1), makePhoto(2), makePhoto(3)]);
    await userEvent.setup().upload(fileInput(before()), files(3));
    expect(await within(before()).findByText("4/4")).toBeInTheDocument();
    expect(uploads("before")).toHaveLength(1);
  });

  it("shows 'Uploading…' and disables the tile while uploading, then resets the input", async () => {
    await open();
    const gate = deferred();
    server.use(
      http.post(`${API}/jobs/:id/photos`, async () => {
        await gate.promise;
        return HttpResponse.json(makePhoto(50));
      }),
    );
    const input = fileInput(before());
    try {
      await userEvent.setup().upload(input, file("a.jpg"));
      const busy = await within(before()).findByRole("button", { name: "Uploading…" });
      expect(busy).toBeDisabled();
      expect(input.value).not.toBe("");
    } finally {
      gate.release();
    }
    await waitFor(() => expect(within(before()).queryByRole("button", { name: "Uploading…" })).not.toBeInTheDocument());
    expect(input.value).toBe("");
  });

  it("keeps the photo that uploaded when a later file fails, and shows the error", async () => {
    const state = await open();
    let calls = 0;
    server.use(
      http.post(`${API}/jobs/:id/photos`, () => {
        if (++calls === 2) return HttpResponse.json({ detail: "That photo is too large" }, { status: 413 });
        state.photos = [...state.photos, makePhoto(60)];
        return HttpResponse.json(makePhoto(60));
      }),
    );
    await userEvent.setup().upload(fileInput(before()), files(2));
    expect(await screen.findByRole("alert")).toHaveTextContent("That photo is too large");
    expect(await within(before()).findByRole("img", { name: "Before photo 1" })).toBeInTheDocument();
    expect(within(before()).getByText("1/4")).toBeInTheDocument();
  });

  it("clears a previous error when a new upload starts", async () => {
    await open();
    const user = userEvent.setup();
    server.use(http.post(`${API}/jobs/:id/photos`, () => HttpResponse.json({ detail: "Upload broke" }, { status: 500 })));
    await user.upload(fileInput(before()), file("a.jpg"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Upload broke");

    const gate = deferred();
    server.use(
      http.post(`${API}/jobs/:id/photos`, async () => {
        await gate.promise;
        return HttpResponse.json(makePhoto(70));
      }),
    );
    try {
      await user.upload(fileInput(before()), file("b.jpg"));
      await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
      expect(within(before()).getByRole("button", { name: "Uploading…" })).toBeInTheDocument();
    } finally {
      gate.release();
    }
  });

  it("removes a photo with DELETE and refreshes", async () => {
    await open([makePhoto(7), makePhoto(8)]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Remove before photo 1" }));
    await waitFor(() => expect(within(before()).getByText("1/4")).toBeInTheDocument());
    expect(find("DELETE", "/api/jobs/j1/photos/7")).toHaveLength(1);
    expect(within(before()).getAllByRole("img")).toHaveLength(1);
  });

  it("shows the error and still refreshes when a delete fails", async () => {
    const state = await open([makePhoto(7)]);
    server.use(
      http.delete(`${API}/jobs/:id/photos/:photoId`, () => {
        state.photos = []; // the photo was already gone on the server
        return HttpResponse.json({ detail: "Could not delete" }, { status: 500 });
      }),
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Remove before photo 1" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not delete");
    await waitFor(() => expect(within(before()).queryByRole("img")).not.toBeInTheDocument());
  });

  it("has no add or remove controls when the job isn't editable, and says 'No photos.' for an empty kind", async () => {
    await open([makePhoto(1)], makeJob({ status: "VERIFIED" }));
    expect(screen.queryByRole("button", { name: /^Remove/ })).not.toBeInTheDocument();
    expect(fileInput(before())).toBeNull();
    expect(fileInput(after())).toBeNull();
    expect(within(before()).queryByText("No photos.")).not.toBeInTheDocument();
    expect(within(after()).getByText("No photos.")).toBeInTheDocument();
  });

  it("points each image at photoUrl and labels it by position", async () => {
    await open([makePhoto(7), makePhoto(9), makePhoto(11, "after")]);
    expect(within(before()).getByRole("img", { name: "Before photo 1" })).toHaveAttribute("src", photoUrl("j1", 7));
    expect(within(before()).getByRole("img", { name: "Before photo 2" })).toHaveAttribute("src", photoUrl("j1", 9));
    expect(within(after()).getByRole("img", { name: "After photo 1" })).toHaveAttribute("src", photoUrl("j1", 11));
  });
});
